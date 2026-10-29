"""Lease-based worker for offline-only scheduled publication simulations."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from . import blogger_drafts
from .db import connection
from .publications import FakeBloggerPublisher
from .worker import heartbeat


def retryable(outcome: str, scenario: str, retry_count: int, max_retries: int) -> bool:
    return (
        outcome == "failed"
        and scenario in {"timeout", "server_failure"}
        and retry_count < max_retries
    )


def _append_audit(conn: Any, event_type: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
        (event_type, Jsonb(payload)),
    )


def tick(
    backoff_seconds: int = 30, *, allow_private_drafts: bool = False
) -> dict[str, Any] | None:
    """Process one explicitly approved private draft or one due fake job."""
    if not 0 <= backoff_seconds <= 3600:
        raise ValueError("invalid_backoff")
    if allow_private_drafts:
        draft = blogger_drafts.process_next_queued_draft()
        if draft is not None:
            return {
                "job_type": "blogger_private_draft",
                **draft,
                "private_draft_creation_enabled": True,
                "public_publication_enabled": False,
                "simulation_only": False,
            }
    with connection() as conn:
        recovered = conn.execute(
            """SELECT id,attempts,max_retries,publication_state FROM publishing_jobs
            WHERE status='running' AND lease_until < now() AND simulation_only AND adapter_type='fake'
            FOR UPDATE SKIP LOCKED"""
        ).fetchall()
        for old in recovered:
            retry = int(old["attempts"]) <= int(old["max_retries"])
            next_status = "queued" if retry else "failed"
            conn.execute(
                """UPDATE publishing_jobs SET status=%s,lease_until=NULL,
                    retry_count=retry_count+1,available_at=now(),last_error_category='lease_expired',updated_at=now()
                    WHERE id=%s""",
                (next_status, old["id"]),
            )
            _append_audit(
                conn,
                "publication.worker.lease_recovered",
                {
                    "job_id": str(old["id"]),
                    "status": next_status,
                    "domain_state_unchanged": old["publication_state"],
                },
            )
        job = conn.execute(
            """SELECT id,attempts,retry_count,max_retries,mock_scenario,publication_state
            FROM publishing_jobs WHERE status='queued' AND scheduled_at<=now() AND available_at<=now()
              AND simulation_only AND adapter_type='fake'
            ORDER BY scheduled_at,id FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if job is None:
            return None
        attempt_no = int(job["attempts"]) + 1
        conn.execute(
            """UPDATE publishing_jobs SET status='running',attempts=%s,
                lease_until=now()+interval '60 seconds',last_error_category=NULL,updated_at=now()
                WHERE id=%s""",
            (attempt_no, job["id"]),
        )
        _append_audit(
            conn,
            "publication.worker.started",
            {
                "job_id": str(job["id"]),
                "attempt_no": attempt_no,
                "adapter_type": "fake",
                "simulation_only": True,
            },
        )
        prior = conn.execute(
            "SELECT id,outcome,result FROM publication_attempts WHERE job_id=%s AND attempt_no=%s AND attempt_kind='worker'",
            (job["id"], attempt_no),
        ).fetchone()
        attempt_key = f"worker-{job['id']}-attempt-{attempt_no}"
        if prior:
            result = dict(prior["result"])
            outcome = str(prior["outcome"])
            attempt_id = prior["id"]
            reused = True
        else:
            result = FakeBloggerPublisher().publish(str(job["mock_scenario"]))
            outcome = str(result["outcome"])
            attempt = conn.execute(
                """INSERT INTO publication_attempts(job_id,idempotency_key,scenario,outcome,fake_post_id,
                    result,attempt_no,attempt_kind,retryable) VALUES (%s,%s,%s,%s,%s,%s,%s,'worker',%s) RETURNING id""",
                (
                    job["id"],
                    attempt_key,
                    job["mock_scenario"],
                    outcome,
                    result["fake_post_id"],
                    Jsonb(result),
                    attempt_no,
                    job["mock_scenario"] in {"timeout", "server_failure"},
                ),
            ).fetchone()
            assert attempt is not None
            attempt_id = attempt["id"]
            reused = False
        scenario = str(job["mock_scenario"])
        can_retry = scenario in {"timeout", "server_failure"}
        should_retry = retryable(
            outcome, scenario, int(job["retry_count"]), int(job["max_retries"])
        )
        if should_retry:
            next_status = "queued"
            conn.execute(
                """UPDATE publishing_jobs SET status='queued',retry_count=retry_count+1,
                    lease_until=NULL,available_at=now()+(%s * interval '1 second'),
                    last_error_category=%s,updated_at=now() WHERE id=%s""",
                (backoff_seconds, scenario, job["id"]),
            )
            event_type = "publication.worker.retry_scheduled"
        elif outcome == "succeeded":
            next_status = "succeeded"
            conn.execute(
                "UPDATE publishing_jobs SET status='succeeded',lease_until=NULL,updated_at=now() WHERE id=%s",
                (job["id"],),
            )
            event_type = "publication.worker.completed"
        else:
            next_status = "uncertain" if outcome == "uncertain" else "failed"
            conn.execute(
                "UPDATE publishing_jobs SET status=%s,lease_until=NULL,last_error_category=%s,updated_at=now() WHERE id=%s",
                (next_status, scenario, job["id"]),
            )
            event_type = "publication.worker.failed"
        _append_audit(
            conn,
            event_type,
            {
                "job_id": str(job["id"]),
                "attempt_id": str(attempt_id),
                "attempt_no": attempt_no,
                "outcome": outcome,
                "next_status": next_status,
                "retryable": should_retry,
                "retry_policy_allows": can_retry,
                "attempt_reused": reused,
                "simulation_only": True,
                "external_network_calls": 0,
                "domain_publication_state_unchanged": job["publication_state"],
                "publish_ready": False,
            },
        )
        return {
            "job_id": str(job["id"]),
            "attempt_id": str(attempt_id),
            "attempt_no": attempt_no,
            "status": next_status,
            "outcome": outcome,
            "scenario": scenario,
            "retryable": should_retry,
            "retry_policy_allows": can_retry,
            "attempt_reused": reused,
            "simulation_only": True,
            "real_writes_enabled": False,
            "domain_publication_state": job["publication_state"],
            "publish_ready": False,
        }


def run_once(
    backoff_seconds: int = 30, *, allow_private_drafts: bool = False
) -> dict[str, Any]:
    heartbeat("running", service_name="publication_worker")
    try:
        result = tick(backoff_seconds, allow_private_drafts=allow_private_drafts)
        return {
            "processed": result is not None,
            "result": result,
            "private_draft_creation_enabled": allow_private_drafts,
            "public_publication_enabled": False,
        }
    except Exception:
        heartbeat("degraded", "publication_worker_failed", "publication_worker")
        raise
    finally:
        heartbeat("stopped", service_name="publication_worker")
