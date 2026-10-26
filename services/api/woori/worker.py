"""Durable diagnostic and internal research worker; no external publication."""

import os
import threading
import time

import psycopg
from psycopg.types.json import Jsonb

from . import collection, pipeline
from .db import connection


def heartbeat(status: str = "running", error_category: str | None = None) -> None:
    if status not in {"running", "degraded"}:
        raise ValueError("invalid_worker_status")
    with connection() as conn:
        previous = conn.execute(
            "SELECT process_id,status,last_error_category FROM worker_heartbeats WHERE service_name='research_worker'"
        ).fetchone()
        conn.execute(
            """INSERT INTO worker_heartbeats(service_name,process_id,status,last_error_category,last_seen_at,updated_at)
            VALUES ('research_worker',%s,%s,%s,now(),now())
            ON CONFLICT(service_name) DO UPDATE SET process_id=EXCLUDED.process_id,status=EXCLUDED.status,
              last_error_category=EXCLUDED.last_error_category,last_seen_at=now(),updated_at=now()""",
            (os.getpid(), status, error_category),
        )
        if previous is None or (
            int(previous["process_id"]) != os.getpid()
            or previous["status"] != status
            or previous["last_error_category"] != error_category
        ):
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('worker.status.changed',%s)",
                (Jsonb({"service": "research_worker", "status": status,
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


def main() -> None:
    stop = threading.Event()
    degraded = threading.Event()

    def beat() -> None:
        while not stop.is_set():
            try:
                heartbeat("degraded" if degraded.is_set() else "running",
                          "database_unavailable" if degraded.is_set() else None)
            except psycopg.Error:
                degraded.set()
            stop.wait(15)

    heartbeat_thread = threading.Thread(target=beat, name="research-worker-heartbeat", daemon=True)
    heartbeat_thread.start()
    while True:
        try:
            collection.schedule_tick()
            collection.tick()
            pipeline.schedule_tick()
            pipeline.tick()
            tick()
        except psycopg.Error:
            degraded.set()
            print("Database unavailable; reconnecting without logging credentials", flush=True)
        else:
            degraded.clear()
        time.sleep(5)


if __name__ == "__main__":
    main()
