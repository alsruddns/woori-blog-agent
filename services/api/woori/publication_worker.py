"""Lease-based worker for offline-only scheduled publication simulations."""

from __future__ import annotations

from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from . import blogger_drafts, external_policy, publications
from .blogger_writes import BloggerLivePublisher
from .db import connection
from .google_http import GoogleFailure
from .publication_daily import (
    GLOBAL_DAILY_PUBLISH_LIMIT,
    LANGUAGE_DAILY_LIMITS,
    LANGUAGE_HOURLY_LIMITS,
    kst_day_bounds,
)
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


def _live_attempt(
    conn: Any, job_id: UUID, attempt_no: int, operation: str, key: str,
    outcome: str, *, post_id: str | None = None, status: int | None = None,
    category: str | None = None, metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO live_publication_attempts(job_id,attempt_no,operation,idempotency_key,
        outcome,remote_post_id,http_status,error_category,metadata)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(job_id,attempt_no,operation) DO NOTHING""",
        (job_id, attempt_no, operation, key, outcome, post_id, status, category,
         Jsonb(metadata or {})),
    )


def process_next_live_job() -> dict[str, Any] | None:
    """Process one fully approved Blogger job; all absent approvals fail closed."""
    with connection() as conn:
        relation = conn.execute(
            "SELECT to_regclass('public.live_publication_attempts') AS ready"
        ).fetchone()
        if not relation or not relation["ready"]:
            return None
        expired = conn.execute(
            """SELECT id,live_stage,publication_state FROM publishing_jobs
              WHERE NOT simulation_only AND adapter_type='blogger_live' AND status='running'
                AND lease_until<now() FOR UPDATE SKIP LOCKED"""
        ).fetchall()
        for old in expired:
            conn.execute(
                """UPDATE publishing_jobs SET status='uncertain',publication_state='publication_blocked',
                  last_error_category='lease_expired_remote_reconciliation_required',lease_until=NULL,updated_at=now()
                  WHERE id=%s""", (old["id"],)
            )
            _append_audit(conn, "publication.live_job.lease_uncertain", {
                "job_id": str(old["id"]), "stage": old["live_stage"],
                "reason": "remote_reconciliation_required", "automatic_replay": False,
            })
        if expired:
            return {"status": "uncertain", "recovered_jobs": len(expired), "live_write_performed": False}
        day = __import__("datetime").datetime.now(ZoneInfo("Asia/Seoul")).date()
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                     ("blogger-live-global-daily:" + str(day),))
        job = conn.execute(
            """SELECT id,policy_id,blog_id,content_version_id,idempotency_key,attempts,
            retry_count,max_retries,publication_state,live_stage,remote_post_id,oauth_connection_id
            FROM publishing_jobs j WHERE NOT j.simulation_only AND j.adapter_type='blogger_live'
              AND j.status='queued' AND j.scheduled_at<=now() AND j.available_at<=now()
            ORDER BY CASE WHEN (SELECT language_code FROM blogger_blogs bb WHERE bb.id=j.blog_id)='en'
              THEN 0 ELSE 1 END,j.scheduled_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if job is None:
            return None
        job_id = UUID(str(job["id"]))
        blog_id = UUID(str(job["blog_id"]))
        version_id = UUID(str(job["content_version_id"]))
        candidate = publications._candidate(conn, version_id, blog_id)
        reasons = list(publications._assess(dict(candidate) if candidate else None)["reasons"])
        current = conn.execute(
            "SELECT oauth_connection_id,blog_id FROM blogger_blogs WHERE id=%s AND active",
            (blog_id,),
        ).fetchone()
        if not current or str(current["oauth_connection_id"]) != str(job["oauth_connection_id"]):
            reasons.append("blog_oauth_mapping_changed")
        if not external_policy._blogger_operation_is_approved("blogger_public_publish"):
            reasons.append("separate_public_publish_operations_approval_required")
        settings = conn.execute(
            """SELECT emergency_stopped FROM publication_mode_settings
            WHERE scope_type='global' AND scope_key=''"""
        ).fetchone()
        if not settings or settings["emergency_stopped"]:
            reasons.append("global_emergency_stop_or_policy_missing")
        if reasons:
            final_reasons = sorted(set(reasons))
            conn.execute(
                """UPDATE publishing_jobs SET status='blocked',publication_state='publication_blocked',
                block_reasons=%s,lease_until=NULL,updated_at=now() WHERE id=%s""",
                (Jsonb(final_reasons), job_id),
            )
            conn.execute(
                """INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details)
                VALUES (%s,%s,'publication_blocked','live_eligibility_recheck_failed',%s)""",
                (job_id, job["publication_state"], Jsonb({"reasons": final_reasons})),
            )
            _append_audit(conn, "publication.live_job.blocked", {
                "job_id": str(job_id), "content_version_id": str(version_id),
                "reasons": final_reasons, "network_calls": 0,
            })
            return {"job_id": str(job_id), "status": "blocked", "reasons": final_reasons,
                    "live_write_performed": False}

        assert candidate is not None
        blog = conn.execute(
            "SELECT language_code,blog_id,url FROM blogger_blogs WHERE id=%s", (blog_id,)
        ).fetchone()
        language = str(blog["language_code"])
        today = __import__("datetime").datetime.now(ZoneInfo("Asia/Seoul")).date()
        day_start, day_end = kst_day_bounds(today)
        daily = conn.execute(
            """WITH actual AS (
              SELECT b.language_code,count(*)::int AS n FROM publishing_records r
              JOIN blogger_blogs b ON b.id=r.blog_id WHERE r.published_at>=%s AND r.published_at<%s
              GROUP BY b.language_code
            ), reserved AS (
              SELECT b.language_code,count(*)::int AS n FROM publishing_jobs j
              JOIN blogger_blogs b ON b.id=j.blog_id
              WHERE NOT j.simulation_only AND j.adapter_type='blogger_live'
                AND j.status IN ('queued','running','uncertain') AND j.scheduled_at>=%s AND j.scheduled_at<%s
              GROUP BY b.language_code
            ) SELECT COALESCE((SELECT sum(n) FROM actual),0)::int AS actual_total,
              COALESCE((SELECT sum(n) FROM reserved),0)::int AS reserved_total,
              COALESCE((SELECT n FROM actual WHERE language_code=%s),0)::int AS lang_actual,
              COALESCE((SELECT n FROM reserved WHERE language_code=%s),0)::int AS lang_reserved""",
            (day_start, day_end, day_start, day_end, language, language),
        ).fetchone()
        language_cap = LANGUAGE_DAILY_LIMITS.get(language)
        if (int(daily["actual_total"])+int(daily["reserved_total"])>GLOBAL_DAILY_PUBLISH_LIMIT
                or (language_cap is not None and int(daily["lang_actual"])+int(daily["lang_reserved"])>language_cap)):
            return {"job_id": str(job_id), "status": "deferred", "reason": "daily_publication_limit",
                    "live_write_performed": False}
        hourly = conn.execute(
            """SELECT count(*)::int AS actual FROM publishing_records
            WHERE blog_id=%s AND published_at>=now()-interval '1 hour'""", (blog_id,)
        ).fetchone()["actual"]
        hourly_reserved = conn.execute(
            """SELECT count(*)::int AS reserved FROM publishing_jobs
            WHERE blog_id=%s AND NOT simulation_only AND adapter_type='blogger_live'
              AND status IN ('queued','running','uncertain') AND scheduled_at>=now()-interval '1 hour'""",
            (blog_id,),
        ).fetchone()["reserved"]
        hourly_cap = LANGUAGE_HOURLY_LIMITS.get(language, 0)
        if int(hourly)+int(hourly_reserved)>hourly_cap:
            return {"job_id": str(job_id), "status": "deferred", "reason": "hourly_publication_limit",
                    "live_write_performed": False}

        attempt_no = int(job["attempts"])+1
        claimed = conn.execute(
            """UPDATE publishing_jobs SET status='running',publication_state='publishing',
            attempts=%s,lease_until=now()+interval '120 seconds',updated_at=now()
            WHERE id=%s AND status='queued' RETURNING live_stage,remote_post_id""",
            (attempt_no, job_id),
        ).fetchone()
        if not claimed:
            return None
        _append_audit(conn, "publication.live_job.started", {
            "job_id": str(job_id), "attempt_no": attempt_no,
            "stage": claimed["live_stage"], "adapter_type": "blogger_live",
            "simulation_only": False, "content_version_id": str(version_id),
        })

    publisher = BloggerLivePublisher()
    stage = str(claimed["live_stage"])
    if stage == "draft_needed":
        operation = "create_draft"
        write_key = "pubjob-" + str(job_id) + "-draft"
        try:
            result = publisher.create_draft(
                write_key, blog_id,
                str(candidate.get("editorial_title") or candidate["title"]),
                str(candidate["html_body"]),
            )
            with connection() as conn:
                conn.execute(
                    """UPDATE publishing_jobs SET status='queued',publication_state='publication_queued',
                    live_stage='draft_created',remote_post_id=%s,available_at=now()+interval '5 minutes',
                    lease_until=NULL,updated_at=now() WHERE id=%s AND status='running'""",
                    (result["post_id"], job_id),
                )
                _live_attempt(conn, job_id, attempt_no, operation, write_key, "succeeded",
                              post_id=str(result["post_id"]), status=result.get("http_status"),
                              metadata={"draft_readback_verified": bool(result.get("post_verified"))})
                _append_audit(conn, "publication.live_draft.created", {
                    "job_id": str(job_id), "content_version_id": str(version_id),
                    "blog_id": str(blog["blog_id"]), "post_id": str(result["post_id"]),
                    "private": True, "public_write_performed": False,
                })
            return {"job_id": str(job_id), "status": "draft_created", "post_id": result["post_id"],
                    "next_stage_after_minutes": 5, "public_write_performed": False}
        except GoogleFailure as exc:
            status = "uncertain" if exc.category in {"uncertain_write", "previous_write_pending_or_uncertain", "idempotency_ledger_unavailable"} else "failed"
            with connection() as conn:
                conn.execute(
                    """UPDATE publishing_jobs SET status=%s,publication_state='publication_failed',
                    last_error_category=%s,lease_until=NULL,updated_at=now() WHERE id=%s AND status='running'""",
                    (status, exc.category, job_id),
                )
                _live_attempt(conn, job_id, attempt_no, operation, write_key, status, status=exc.status, category=exc.category)
                _append_audit(conn, "publication.live_draft.failed", {
                    "job_id": str(job_id), "error_category": exc.category,
                    "http_status": exc.status, "post_write_replayed": False,
                })
            return {"job_id": str(job_id), "status": status, "reason": exc.category,
                    "public_write_performed": False}

    if stage != "draft_created" or not claimed["remote_post_id"]:
        with connection() as conn:
            conn.execute(
                """UPDATE publishing_jobs SET status='uncertain',publication_state='publication_blocked',
                last_error_category='live_job_stage_invalid',lease_until=NULL,updated_at=now() WHERE id=%s""",
                (job_id,),
            )
        return {"job_id": str(job_id), "status": "uncertain", "reason": "live_job_stage_invalid"}
    operation = "publish_draft"
    source_draft_key = "pubjob-" + str(job_id) + "-draft"
    write_key = "pubjob-" + str(job_id) + "-publish"
    try:
        result = publisher.publish_draft(
            write_key, blog_id, str(claimed["remote_post_id"]),
            source_draft_key=source_draft_key,
        )
        if result.get("status") != "LIVE" or not result.get("readback_verified"):
            raise GoogleFailure("published_readback_mismatch")
        with connection() as conn:
            conn.execute(
                """INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,
                published_at,remote_url,remote_status,remote_verified_at)
                VALUES (%s,%s,%s,%s,%s,%s,'LIVE',now()) ON CONFLICT(blog_id,content_version_id) DO NOTHING""",
                (job_id, blog_id, version_id, result["post_id"], result["published_at"], result["url"]),
            )
            record = conn.execute(
                "SELECT remote_post_id,remote_url FROM publishing_records WHERE blog_id=%s AND content_version_id=%s",
                (blog_id, version_id),
            ).fetchone()
            if not record or record["remote_post_id"] != result["post_id"] or record["remote_url"] != result["url"]:
                raise GoogleFailure("published_record_conflict")
            conn.execute(
                """UPDATE publishing_jobs SET status='succeeded',publication_state='published',
                live_stage='published',remote_post_id=%s,lease_until=NULL,last_error_category=NULL,updated_at=now()
                WHERE id=%s AND status='running'""",
                (result["post_id"], job_id),
            )
            _live_attempt(conn, job_id, attempt_no, operation, write_key, "succeeded",
                          post_id=str(result["post_id"]), status=result.get("http_status"),
                          metadata={"readback_verified": True, "url": result["url"]})
            conn.execute(
                """INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details)
                VALUES (%s,'publishing','published','blogger_remote_readback_verified',%s)""",
                (job_id, Jsonb({"post_id": result["post_id"], "url": result["url"],
                                "published_at": result["published_at"], "readback_verified": True})),
            )
            _append_audit(conn, "publication.live_job.published", {
                "job_id": str(job_id), "content_version_id": str(version_id),
                "blog_id": str(blog["blog_id"]), "post_id": result["post_id"],
                "url": result["url"], "published_at": result["published_at"],
                "remote_readback_verified": True,
            })
        return {"job_id": str(job_id), "status": "published", "post_id": result["post_id"],
                "url": result["url"], "remote_readback_verified": True}
    except GoogleFailure as exc:
        status = "uncertain" if exc.category in {"uncertain_write", "previous_write_pending_or_uncertain", "idempotency_ledger_unavailable", "published_readback_mismatch", "published_record_conflict"} else "failed"
        with connection() as conn:
            conn.execute(
                """UPDATE publishing_jobs SET status=%s,publication_state='publication_failed',
                last_error_category=%s,lease_until=NULL,updated_at=now() WHERE id=%s AND status='running'""",
                (status, exc.category, job_id),
            )
            _live_attempt(conn, job_id, attempt_no, operation, write_key, status,
                          post_id=str(claimed["remote_post_id"]), status=exc.status, category=exc.category)
            _append_audit(conn, "publication.live_job.failed", {
                "job_id": str(job_id), "error_category": exc.category,
                "http_status": exc.status, "post_write_replayed": False,
            })
        return {"job_id": str(job_id), "status": status, "reason": exc.category,
                "public_write_performed": False}


def tick(
    backoff_seconds: int = 30, *, allow_private_drafts: bool = False
) -> dict[str, Any] | None:
    """Process one explicitly approved private draft or one due fake job."""
    if not 0 <= backoff_seconds <= 3600:
        raise ValueError("invalid_backoff")
    live = process_next_live_job()
    if live is not None:
        return {"job_type": "blogger_live", **live, "simulation_only": False,
                "auto_enabled": False}
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
