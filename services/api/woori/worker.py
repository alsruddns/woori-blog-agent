"""Durable diagnostic and internal research worker; no external publication."""

import os
import signal
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb

from . import collection, pipeline, scheduled_import_inbox, topics, trends
from .config import settings
from .db import connection

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEDULED_IMPORT_POLL_SECONDS = 60
WORKER_LOCK_KEYS = {"research_worker": (20261027, 26027), "evaluation_worker": (20261027, 26028)}


def acquire_process_lock(service_name: str) -> psycopg.Connection:
    """Hold a DB session lock for this worker lifetime so a second process exits safely."""
    key = WORKER_LOCK_KEYS.get(service_name)
    if key is None:
        raise ValueError("invalid_worker_service")
    guard = psycopg.connect(settings().database_url, autocommit=True)
    acquired = guard.execute(
        "SELECT pg_try_advisory_lock(%s,%s)", key
    ).fetchone()
    if not acquired or not acquired[0]:
        guard.close()
        raise SystemExit("another_worker_holds_singleton_lock")
    return guard


def release_process_lock(guard: psycopg.Connection, service_name: str) -> None:
    key = WORKER_LOCK_KEYS[service_name]
    try:
        try:
            guard.execute("SELECT pg_advisory_unlock(%s,%s)", key)
        except psycopg.Error:
            # A lost session releases its PostgreSQL advisory locks automatically.
            # Do not mask the original worker shutdown error while closing it.
            pass
    finally:
        guard.close()


def heartbeat(
    status: str = "running", error_category: str | None = None,
    service_name: str = "research_worker",
) -> None:
    if status not in {"running", "degraded", "stopped"}:
        raise ValueError("invalid_worker_status")
    if service_name not in {"research_worker", "evaluation_worker", "publication_worker"}:
        raise ValueError("invalid_worker_service")
    with connection() as conn:
        previous = conn.execute(
            "SELECT process_id,status,last_error_category FROM worker_heartbeats WHERE service_name=%s",
            (service_name,),
        ).fetchone()
        conn.execute(
            """INSERT INTO worker_heartbeats(service_name,process_id,status,last_error_category,last_seen_at,updated_at)
            VALUES (%s,%s,%s,%s,now(),now())
            ON CONFLICT(service_name) DO UPDATE SET process_id=EXCLUDED.process_id,status=EXCLUDED.status,
              last_error_category=EXCLUDED.last_error_category,last_seen_at=now(),updated_at=now()""",
            (service_name, os.getpid(), status, error_category),
        )
        if previous is None or (
            int(previous["process_id"]) != os.getpid()
            or previous["status"] != status
            or previous["last_error_category"] != error_category
        ):
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('worker.status.changed',%s)",
                (Jsonb({"service": service_name, "status": status,
                        "error_category": error_category, "process_id": os.getpid()}),),
            )


def tick() -> bool:
    with connection() as conn:
        # Recover interrupted leases atomically; never repeat an external side effect.
        recovered = conn.execute("""UPDATE job_runs SET status=CASE WHEN attempts>=3 THEN 'failed'
            ELSE 'queued' END, lease_until=NULL, error_type='LeaseExpired',
            error_message='Worker lease expired', error_location='worker', error_at=now(),
            resolution='Recovered expired lease', updated_at=now()
            WHERE task_kind='diagnostic' AND status='running' AND lease_until<now() RETURNING id,status""").fetchall()
        for item in recovered:
            conn.execute(
                "INSERT INTO audit_events(run_id,event_type,payload) VALUES (%s,%s,%s)",
                (item["id"], "run." + item["status"], '{"reason":"lease_expired"}'),
            )
        row = conn.execute("""SELECT id, attempts FROM job_runs WHERE task_kind='diagnostic' AND status='queued' AND available_at<=now()
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if row is None:
            return False
        run_id = row["id"]
        conn.execute(
            """UPDATE job_runs SET status='running', attempts=attempts+1,
            lease_until=now()+interval '60 seconds',updated_at=now() WHERE id=%s""",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO audit_events(run_id,event_type) VALUES (%s,'run.started')", (run_id,)
        )
    # Diagnostic work has no external effects. Future adapters require an outbox and reconciliation.
    with connection() as conn:
        completed = conn.execute(
            """UPDATE job_runs SET status='succeeded',lease_until=NULL,
            resolution='Diagnostic completed',updated_at=now()
            WHERE id=%s AND status='running' AND attempts=%s RETURNING id""",
            (run_id, row["attempts"] + 1),
        ).fetchone()
        if completed is None:
            return False
        conn.execute(
            "INSERT INTO audit_events(run_id,event_type) VALUES (%s,'run.completed')", (run_id,)
        )
    return True


def collect_trends_and_build_topics() -> dict[str, object]:
    """Build exact-query, evidence-gated candidates only after a real feed collection."""
    result = trends.schedule_tick()
    if result.get("status") == "succeeded":
        result["candidate_build"] = topics.build_candidates()
        result["research_triage"] = topics.select_research_candidates(
            settings().trend_research_hourly_limit
        )
    return result


def scheduled_import_intake_tick() -> dict[str, object]:
    """Poll the fixed local inbox, import review-held files, and audit file outcomes."""
    with connection() as lock_conn:
        claim = lock_conn.execute(
            "SELECT pg_try_advisory_lock(20261029,24024) AS acquired"
        ).fetchone()
        if not claim or not claim["acquired"]:
            return {"processed_count": 0, "results": [], "skipped": "another_worker_holds_inbox_lock"}
        try:
            result = scheduled_import_inbox.process_inbox_once(
                PROJECT_ROOT / ".local" / "gpt-scheduled-import",
                "http://127.0.0.1:8100",
                settings().admin_token,
                operations_target_confirmed=True,
            )
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(20261029,24024)")
    if result["results"]:
        with connection() as conn:
            for item in result["results"]:
                payload = {
                    key: item.get(key)
                    for key in (
                        "file_key", "file_sha256", "status", "reason", "http_status",
                        "import_id", "audit_event_id", "duplicate",
                        "machine_assessment_passed", "independent_source_verification",
                    )
                    if item.get(key) is not None
                }
                payload.update({
                    "api_origin": "127.0.0.1:8100",
                    "content_review_required": True,
                    "publish_ready": False,
                    "blogger_writes": 0,
                })
                conn.execute(
                    "INSERT INTO audit_events(event_type,payload) VALUES ('scheduled_import.file_outcome',%s)",
                    (Jsonb(payload),),
                )
    return result


def _evaluation_database_isolated() -> None:
    operations_url = os.environ.get("WOORI_OPERATION_DATABASE_URL", "")
    if not operations_url:
        raise SystemExit("Evaluation worker requires a separate operations database reference")
    from .config import settings

    evaluation_target = urlparse(settings().database_url)
    operations_target = urlparse(operations_url)
    if not evaluation_target.path or not operations_target.path:
        raise SystemExit("Evaluation database identity is unavailable")
    with connection() as conn:
        state = conn.execute(
            "SELECT current_database() AS name,(SELECT evaluation_isolated FROM pipeline_controls) AS isolated"
        ).fetchone()
    if state is None:
        raise SystemExit("Evaluation database policy is unavailable")
    with psycopg.connect(operations_url) as conn:
        operations_row = conn.execute("SELECT current_database()").fetchone()
    if operations_row is None:
        raise SystemExit("Operations database identity is unavailable")
    operations_name = operations_row[0]
    if not state["isolated"] or state["name"] == operations_name:
        raise SystemExit("Evaluation worker refused a shared or unapproved database")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the local durable research worker")
    parser.add_argument("--evaluation", action="store_true", help="Consume only the isolated evaluation queue")
    parser.add_argument("--once", action="store_true", help="Process at most one job, only in evaluation mode")
    parser.add_argument("--diagnostic-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-seconds", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run_seconds < 0 or args.run_seconds > 3600:
        raise SystemExit("run-seconds must be between 0 and 3600")
    evaluation_mode = bool(args.evaluation)
    if args.once and not evaluation_mode:
        raise SystemExit("--once is reserved for the isolated evaluation worker")
    if evaluation_mode and args.diagnostic_only:
        raise SystemExit("Worker modes are mutually exclusive")
    if evaluation_mode:
        _evaluation_database_isolated()
    service_name = "evaluation_worker" if evaluation_mode else "research_worker"
    process_guard = acquire_process_lock(service_name)
    started_at = time.monotonic()
    next_scheduled_import_poll = started_at
    stop = threading.Event()
    degraded = threading.Event()
    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)

    def beat() -> None:
        while not stop.is_set():
            try:
                heartbeat("degraded" if degraded.is_set() else "running",
                          "database_unavailable" if degraded.is_set() else None, service_name)
            except psycopg.Error:
                degraded.set()
            stop.wait(15)

    heartbeat_thread = threading.Thread(target=beat, name="research-worker-heartbeat", daemon=True)
    heartbeat_thread.start()
    try:
        while not stop.is_set():
            if args.run_seconds and time.monotonic() - started_at >= args.run_seconds:
                break
            try:
                if evaluation_mode:
                    pipeline.tick(evaluation_only=True)
                elif args.diagnostic_only:
                    tick()
                else:
                    # Exact-query topic grouping and evidence scoring are local-only;
                    # it never creates a manuscript or publication by itself.
                    collect_trends_and_build_topics()
                    collection.schedule_tick()
                    collection.tick()
                    pipeline.schedule_tick()
                    pipeline.tick(evaluation_only=False)
                    tick()
                    if time.monotonic() >= next_scheduled_import_poll:
                        next_scheduled_import_poll = time.monotonic() + SCHEDULED_IMPORT_POLL_SECONDS
                        intake = scheduled_import_intake_tick()
                        if intake["processed_count"]:
                            counts = Counter(result["status"] for result in intake["results"])
                            print(
                                "Scheduled import intake completed: "
                                + ",".join(f"{status}={count}" for status, count in sorted(counts.items())),
                                flush=True,
                            )
            except psycopg.Error:
                degraded.set()
                print("Database unavailable; reconnecting without logging credentials", flush=True)
            else:
                degraded.clear()
            if args.once:
                break
            stop.wait(5)
    finally:
        stop.set()
        heartbeat_thread.join(timeout=2)
        try:
            heartbeat("stopped", service_name=service_name)
        except psycopg.Error:
            pass
        release_process_lock(process_guard, service_name)


if __name__ == "__main__":
    main()
