import time
from uuid import uuid4

from woori.db import connection

with connection() as conn:
    run = conn.execute(
        "INSERT INTO job_runs(idempotency_key) VALUES (%s) RETURNING id",
        ("scheduler-verification-" + uuid4().hex,),
    ).fetchone()
    assert run is not None
    run_id = run["id"]
    conn.execute("INSERT INTO audit_events(run_id,event_type) VALUES (%s,'run.queued')", (run_id,))
for _ in range(20):
    with connection() as conn:
        row = conn.execute("SELECT status FROM job_runs WHERE id=%s", (run_id,)).fetchone()
    if row and row["status"] == "succeeded":
        with connection() as audit_db:
            audit_db.execute(
                "INSERT INTO audit_events(run_id,event_type,payload) VALUES (%s,'operations.scheduler.verified','{}')",
                (run_id,),
            )
        print("Scheduled worker executed the durable diagnostic job successfully.")
        break
    time.sleep(1)
else:
    raise SystemExit("Scheduled worker did not complete diagnostic job within 20 seconds")
