"""Durable diagnostic and internal research worker; no external publication."""

import time

import psycopg

from . import collection, pipeline
from .db import connection


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
    while True:
        try:
            collection.schedule_tick()
            collection.tick()
            pipeline.schedule_tick()
            pipeline.tick()
            tick()
        except psycopg.Error:
            print("Database unavailable; reconnecting without logging credentials", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
