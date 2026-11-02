"""Independent bounded lanes. A heartbeat is not proof of stage progress."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .db import bounded_stage_sql, connection

VERSION = "research-stages/1"
LIMITS = {
    "trends_collection": 240,
    "topic_evaluation": 120,
    "research_import": 120,
    "manuscript_generation": None,
}


def audit(conn: Any, event: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES(%s,%s)",
        ("research.stage." + event, Jsonb(payload)),
    )


def progress(
    job: Any,
    checkpoint: str,
    processed: int = 0,
    remaining: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE research_stage_runs SET checkpoint=%s,processed=%s,remaining=%s,
            result=result||%s,last_progress_at=clock_timestamp() WHERE id=%s AND status='running' AND owner_pid=%s""",
            (checkpoint, processed, remaining, Jsonb(details or {}), job, os.getpid()),
        )


def execute(
    stage: str,
    scope: str,
    work: Callable[[Any], dict[str, Any]],
    *,
    engine: str = VERSION,
    settings_id: int = 0,
    repeat: bool = False,
) -> dict[str, Any]:
    """Recover only after the previous owner's *session lock* is gone.

    Elapsed time alone never steals a running task. No process/SQL cancellation.
    Checkpoints and bounded immutable scoring caches survive a process exit.
    """
    key = f"p105:{stage}:{scope}:{engine}:{settings_id}"
    with connection() as guard:
        lock = guard.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) acquired", (key,)
        ).fetchone()
        if not lock or not lock["acquired"]:
            return {"status": "busy"}
        # Session lock remains; do not hold an idle transaction during stage work.
        if "pytest" not in __import__("sys").modules:
            guard.commit()
        try:
            with connection() as conn:
                previous = conn.execute(
                    """SELECT * FROM research_stage_runs WHERE stage=%s AND scope_key=%s
                    AND engine_version=%s AND settings_id=%s FOR UPDATE""",
                    (stage, scope, engine, settings_id),
                ).fetchone()
                if previous and previous["status"] == "completed" and not repeat:
                    return {"status": "cached", "job_id": str(previous["id"])}
                if (
                    previous
                    and previous["status"] in {"failed", "paused", "partial"}
                    and previous["completed_at"]
                    and datetime.now(UTC) - previous["completed_at"] < timedelta(seconds=60)
                ):
                    return {"status": "retry_wait"}
                if previous and previous["status"] == "failed" and previous["attempt"] >= 3:
                    return {"status": "retry_exhausted"}
                row = conn.execute(
                    """INSERT INTO research_stage_runs(stage,scope_key,engine_version,settings_id,status,owner_pid)
                    VALUES(%s,%s,%s,%s,'running',%s) ON CONFLICT(stage,scope_key,engine_version,settings_id) DO UPDATE SET
                    status='running',owner_pid=EXCLUDED.owner_pid,attempt=research_stage_runs.attempt+1,
                    started_at=clock_timestamp(),last_progress_at=clock_timestamp(),completed_at=NULL,error_category=NULL
                    RETURNING id""",
                    (stage, scope, engine, settings_id, os.getpid()),
                ).fetchone()
                assert row is not None
                job = row["id"]
                audit(
                    conn,
                    "started",
                    {
                        "job_id": str(job),
                        "stage": stage,
                        "scope": scope,
                        "recovered_after_lock_release": bool(
                            previous and previous["status"] == "running"
                        ),
                        "prior_checkpoint": previous["checkpoint"] if previous else None,
                    },
                )
            started = time.monotonic()
            try:
                result = work(job)
                state = result.get("stage_status", "completed")
                error = None
            except (psycopg.Error, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                with connection() as conn:
                    saved = conn.execute(
                        "SELECT result FROM research_stage_runs WHERE id=%s", (job,)
                    ).fetchone()
                result = dict(saved["result"]) if saved else {}
                state = "failed"
                error = (
                    "database_wait_timeout"
                    if isinstance(
                        exc, (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled)
                    )
                    else type(exc).__name__
                )
            elapsed = round((time.monotonic() - started) * 1000)
            with connection() as conn:
                conn.execute(
                    """UPDATE research_stage_runs SET status=%s,result=%s,completed_at=clock_timestamp(),
                    last_progress_at=clock_timestamp(),elapsed_ms=%s,error_category=%s WHERE id=%s AND owner_pid=%s""",
                    (state, Jsonb(result), elapsed, error, job, os.getpid()),
                )
                audit(
                    conn,
                    "finished",
                    {
                        "job_id": str(job),
                        "stage": stage,
                        "status": state,
                        "elapsed_ms": elapsed,
                        "error_category": error,
                    },
                )
            return {"job_id": str(job), "status": state, "elapsed_ms": elapsed, "result": result}
        finally:
            guard.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))


def collection_tick(stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    from . import trends
    from .automation_controls import allowed

    if not allowed("trends_collection_enabled"):
        return {"status": "disabled"}
    config = trends.collection_settings()
    slot = trends.configured_slot(datetime.now(UTC), config)

    def work(job: Any) -> dict[str, Any]:
        result = trends.schedule_tick(
            should_stop=stop,
            on_progress=lambda count: progress(
                job, "regions_saved", count, len(trends.ALLOWED_GEOS) - count
            ),
        )
        if result.get("status") in {"busy", "provider_backoff", "disabled"}:
            return {"stage_status": "paused", **result}
        with connection() as conn:
            regions = conn.execute(
                "SELECT geo,result FROM trend_collection_slots WHERE slot_at=%s", (slot,)
            ).fetchall()
            prior = conn.execute(
                "SELECT max(slot_at) stamp FROM trend_collection_slots WHERE slot_at<%s",
                (slot,),
            ).fetchone()
            if (
                prior
                and prior["stamp"]
                and slot - prior["stamp"] > timedelta(minutes=config["interval_minutes"])
            ):
                audit(
                    conn,
                    "missed_slots",
                    {
                        "previous_slot": prior["stamp"].isoformat(),
                        "current_slot": slot.isoformat(),
                        "reason": "collector_not_observed_at_intervening_slots",
                        "replayed": False,
                    },
                )
        successes = sum(r["result"].get("status") == "succeeded" for r in regions)
        state = "completed" if successes == len(trends.ALLOWED_GEOS) else "partial"
        progress(job, "collection_saved", len(regions), len(trends.ALLOWED_GEOS) - len(regions))
        return {
            "stage_status": state,
            "slot": slot.isoformat(),
            "regions": len(regions),
            "successes": successes,
            "failures": len(regions) - successes,
            "collection_result": result.get("status"),
        }

    # Partial regions may receive one bounded transient retry; completed sweeps are cached.
    return execute("trends_collection", slot.isoformat(), work)


def evaluation_tick(stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    from . import editorial_intelligence as engine
    from . import editorial_scoring, trends
    from . import trend_editorial as editorial
    from .automation_controls import allowed

    if not allowed("trends_collection_enabled"):
        return {"status": "disabled"}
    slot = editorial.current_slot()
    with connection() as conn:
        collection = conn.execute(
            "SELECT status FROM research_stage_runs WHERE stage='trends_collection' AND scope_key=%s AND status IN ('completed','partial')",
            (slot.isoformat(),),
        ).fetchone()
        if not collection:
            return {"status": "awaiting_collection"}
        rows = conn.execute(
            "SELECT geo,run_id FROM trend_collection_slots WHERE slot_at=%s AND result->>'status'='succeeded' ORDER BY geo",
            (slot,),
        ).fetchall()
        config = conn.execute(
            "SELECT id FROM editorial_selection_settings WHERE effective_slot<=%s ORDER BY id DESC LIMIT 1",
            (slot,),
        ).fetchone()
    fingerprint = hashlib.sha256(
        str([(r["geo"], str(r["run_id"])) for r in rows]).encode()
    ).hexdigest()[:16]

    def work(job: Any) -> dict[str, Any]:
        def checkpoint(name: str, count: int = 0) -> None:
            if stop() or editorial.current_slot() != slot:
                return
            progress(job, name, count)

        if stop():
            return {"stage_status": "paused"}
        # Only latest-slot membership/classification, max 11*20 provider candidates.
        with connection() as conn:
            saved = conn.execute(
                "SELECT checkpoint,result FROM research_stage_runs WHERE id=%s", (job,)
            ).fetchone()
        prior = saved["checkpoint"] if saved else ""
        finished = {"normalized_and_classified": 1, "scores_saved": 2, "handoff_saved": 3}.get(
            prior, 0
        )
        classified = (
            (saved["result"].get("classified", {}) if saved else {})
            if finished >= 1
            else editorial.reconcile(limit=len(trends.ALLOWED_GEOS) * trends.MAX_ITEMS)
        )
        progress(
            job,
            "normalized_and_classified",
            sum(classified.values()),
            details={"classified": classified},
        )
        if stop() or editorial.current_slot() != slot:
            return {"stage_status": "superseded"}
        scored = (
            (saved["result"].get("scores", {}) if saved else {})
            if finished >= 2
            else engine.assess_current(slot)
        )
        progress(job, "scores_saved", sum(scored.values()), details={"scores": scored})
        if stop() or editorial.current_slot() != slot:
            return {"stage_status": "superseded"}
        queued = editorial.queue_selected()
        editorial.expire_pending()
        dispatched = editorial.dispatch()
        checkpoint("handoff_saved", sum(scored.values()))
        return {
            "classified": classified,
            "scores": scored,
            "queue": queued,
            "dispatch": dispatched,
            "legacy_cross_geo_scan_executed": False,
            "slot": slot.isoformat(),
        }

    return execute(
        "topic_evaluation",
        slot.isoformat() + ":" + fingerprint,
        work,
        engine=editorial_scoring.VERSION,
        settings_id=config["id"] if config else 0,
    )


def lane_loop(
    stage: str, stop: threading.Event, operation: Callable[[], Any], interval: float
) -> None:
    """Each lane gets its own thread, connections, locks and failure boundary."""
    while not stop.is_set():
        try:
            with bounded_stage_sql():
                operation()
        except (psycopg.Error, OSError, RuntimeError, ValueError, KeyError, TypeError):
            # No secret exception text, no process cancellation, next bounded poll.
            print(f"Research lane {stage} unavailable; other lanes continue.", flush=True)
        stop.wait(interval)


def authoring_tick() -> None:
    """Drain current-slot handoffs independently of cached score computation.

    dispatch only admits a durable Job; the existing CLI runner still enforces
    its own single-run lock, quota and current-slot freshness gates.
    """
    from . import keyword_jobs, trend_editorial

    trend_editorial.expire_pending()
    trend_editorial.dispatch()
    keyword_jobs.tick(import_results=False)


def snapshot() -> dict[str, Any]:
    from . import trends
    from .automation_controls import read

    now = datetime.now(UTC)
    with connection() as conn:
        settings = read(conn)
        rows = conn.execute(
            "SELECT * FROM research_stage_runs ORDER BY last_progress_at DESC LIMIT 100"
        ).fetchall()
        latest = conn.execute("""SELECT max(started_at) attempt,max(started_at) FILTER(WHERE status='succeeded') success
            FROM trend_collection_runs""").fetchone()
        heart = conn.execute(
            "SELECT status,last_seen_at FROM worker_heartbeats WHERE service_name='research_worker'"
        ).fetchone()
        authoring = conn.execute(
            "SELECT state,count(*) n,max(updated_at) progress_at FROM codex_authoring_jobs GROUP BY state"
        ).fetchall()
        from .keyword_jobs import authoring_backoff

        pause = authoring_backoff(conn)
        quality = conn.execute(
            "SELECT stage,status,count(*) n FROM editorial_quality_reports GROUP BY stage,status"
        ).fetchall()
        imports = conn.execute(
            "SELECT count(*) n,max(received_at) latest FROM external_content_imports"
        ).fetchone()
        means = conn.execute(
            "SELECT stage,avg(elapsed_ms)::bigint mean_ms FROM research_stage_runs WHERE status='completed' GROUP BY stage"
        ).fetchall()
    assert latest is not None
    delayed = latest["success"] is None or now - latest["success"] > timedelta(
        minutes=settings["interval_minutes"] * 2
    )
    healthy = bool(
        heart
        and heart["status"] == "running"
        and now - heart["last_seen_at"] < timedelta(seconds=45)
    )
    for row in rows:
        limit = LIMITS.get(row["stage"])
        row["stalled_suspected"] = bool(
            row["status"] == "running"
            and limit
            and (now - row["last_progress_at"]).total_seconds() > limit
        )
    return {
        "settings": {
            "collection_enabled": settings["trends_collection_enabled"],
            "authoring_enabled": settings["auto_manuscript_enabled"],
        },
        "health": "disabled"
        if not settings["trends_collection_enabled"]
        else "worker_unavailable"
        if not healthy
        else "collection_delayed"
        if delayed
        else "collecting_normally",
        "last_attempt": latest["attempt"],
        "last_success": latest["success"],
        "collection_delayed": delayed,
        "regions": len(trends.ALLOWED_GEOS),
        "interval_minutes": settings["interval_minutes"],
        "runs": rows,
        "means": means,
        "authoring": authoring,
        "usage_signal": pause,
        "imports": imports,
        "quality": quality,
        "heartbeat_is_stage_progress": False,
        "automatic_publication_enabled": settings["auto_publishing_enabled"],
    }
