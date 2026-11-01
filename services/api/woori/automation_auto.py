"""New-epoch, reviewed-version automatic dispatch; historical queues are untouched."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from . import automation_controls as controls
from .db import connection

AUTO_JOB: ContextVar[str | None] = ContextVar("automation_job", default=None)


@contextmanager
def job_context(job_id: Any) -> Iterator[None]:
    token = AUTO_JOB.set(str(job_id))
    try:
        yield
    finally:
        AUTO_JOB.reset(token)


def context_allowed(operation: str = "") -> bool:
    job = AUTO_JOB.get()
    if not job:
        return False
    with connection() as conn:
        if not controls.job_permitted(conn, job, running=True):
            return False
        state = controls.read(conn)
        return operation != "blogger_public_publish" or state["auto_mode"] == "publish"


def readiness(
    conn: Any, version: UUID, blog: UUID
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    from . import publications

    row = publications._candidate(conn, version, blog)
    if not row:
        return None, {}, ["content_or_blog_unavailable"]
    reasons = [x for x in publications._assess(row)["reasons"] if x != "production_writes_disabled"]
    snapshot = publications._manual_publication_snapshot(conn, dict(row))
    reasons.extend(snapshot["blockers"])
    newest = conn.execute(
        "SELECT id FROM content_versions WHERE group_id=%s AND localization_id IS NOT DISTINCT FROM %s ORDER BY version DESC,created_at DESC LIMIT 1",
        (row["group_id"], row["localization_id"]),
    ).fetchone()
    if not newest or newest["id"] != version:
        reasons.append("stale_version")
    return dict(row), snapshot, sorted(set(reasons))


def enqueue(conn: Any, state: dict[str, Any]) -> int:
    if (
        not state["auto_publishing_enabled"]
        or state["emergency_stop"]
        or state["blogger_api_restricted"]
        or not state["auto_enabled_at"]
    ):
        return 0
    from . import external_policy

    if external_policy._blogger_policy_approval() is None:
        return 0
    rows = conn.execute(
        """SELECT v.id,b.id AS blog_id FROM content_versions v
        JOIN content_localizations l ON l.id=v.localization_id
        JOIN blogger_blogs b ON b.language_code=l.language_code AND b.active
        WHERE b.id=ANY(%s::uuid[]) AND v.created_at>%s
          AND NOT EXISTS(SELECT 1 FROM publishing_jobs j WHERE j.blog_id=b.id AND j.content_version_id=v.id AND NOT j.simulation_only)
        ORDER BY v.created_at,v.id LIMIT 10""",
        (state["auto_blog_ids"], state["auto_enabled_at"]),
    ).fetchall()
    created = 0
    for item in rows:
        row, _snapshot, reasons = readiness(conn, item["id"], item["blog_id"])
        if reasons or row is None:
            continue
        job = conn.execute(
            """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
            scheduled_at,status,publication_state,adapter_type,simulation_only,block_reasons,oauth_connection_id,
            live_stage,publication_lane,publication_mode)
            VALUES(%s,%s,%s,%s,now(),'queued','publication_queued','blogger_live',false,'[]',%s,'draft_needed','scheduled_auto',%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
            (
                row["policy_id"],
                item["blog_id"],
                item["id"],
                f"p103-{item['id']}-{item['blog_id']}",
                row["oauth_connection_id"],
                state["auto_mode"],
            ),
        ).fetchone()
        if not job:
            continue
        conn.execute(
            "INSERT INTO automation_publication_grants(job_id,epoch,lane,publication_mode) VALUES(%s,%s,'auto',%s)",
            (job["id"], state["auto_epoch"], state["auto_mode"]),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('automation.auto_job.created',%s)",
            (
                Jsonb(
                    {
                        "job_id": str(job["id"]),
                        "version_id": str(item["id"]),
                        "epoch": str(state["auto_epoch"]),
                        "mode": state["auto_mode"],
                        "quality_promoted": False,
                    }
                ),
            ),
        )
        created += 1
    return created


def tick(*, publisher: Any = None) -> dict[str, Any] | None:
    from .blogger_writes import BloggerLivePublisher, WriteIntervalWait
    from .google_http import GoogleFailure
    from .publication_worker import save_verified_draft
    from .scheduled_duplicates import find_remote_duplicate

    with connection() as conn:
        lock = conn.execute("SELECT pg_try_advisory_xact_lock(20261102,10301) acquired").fetchone()
        if not lock or not lock["acquired"]:
            return None
        state = controls.read(conn)
        enqueue(conn, state)
        if (
            not state["auto_publishing_enabled"]
            or state["emergency_stop"]
            or state["blogger_api_restricted"]
        ):
            return None
        job = conn.execute(
            """SELECT j.* FROM publishing_jobs j JOIN automation_publication_grants g ON g.job_id=j.id
            WHERE g.lane='auto' AND g.epoch=%s AND j.status='queued' AND j.available_at<=now()
              AND j.scheduled_at<=now() ORDER BY j.scheduled_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (state["auto_epoch"],),
        ).fetchone()
        if not job:
            return None
        row, snapshot, reasons = readiness(conn, job["content_version_id"], job["blog_id"])
        if not controls.job_permitted(conn, job["id"]):
            reasons.append("automation_policy_changed")
        if reasons or row is None:
            conn.execute(
                "UPDATE publishing_jobs SET status='blocked',last_error_category='automatic_quality_or_policy_blocked',updated_at=now() WHERE id=%s",
                (job["id"],),
            )
            return {"job_id": str(job["id"]), "status": "blocked", "reasons": reasons}
        conn.execute(
            "UPDATE publishing_jobs SET status='running',lease_until=now()+interval '2 minutes',updated_at=now() WHERE id=%s",
            (job["id"],),
        )
    publisher = publisher or BloggerLivePublisher()
    try:
        duplicate = find_remote_duplicate(
            job["blog_id"],
            snapshot["title"],
            include_drafts=True,
            exclude_post_id=str(job.get("remote_post_id") or ""),
        )
        if duplicate["status"] != "clear":
            raise GoogleFailure("automatic_duplicate_unconfirmed_or_found")
        with job_context(job["id"]):
            if job["live_stage"] == "draft_needed":
                result = publisher.create_draft(
                    "pubjob-" + str(job["id"]) + "-draft",
                    job["blog_id"],
                    snapshot["title"],
                    snapshot["safe_html"],
                    snapshot["blogger_labels"],
                )
                if job["publication_mode"] == "draft":
                    return save_verified_draft(
                        job["id"], job["blog_id"], job["content_version_id"], result
                    )
                with connection() as conn:
                    conn.execute(
                        "UPDATE publishing_jobs SET status='queued',live_stage='draft_created',remote_post_id=%s,available_at=now()+interval '5 minutes',lease_until=NULL,updated_at=now() WHERE id=%s",
                        (result["post_id"], job["id"]),
                    )
                return {"job_id": str(job["id"]), "status": "draft_created"}
            result = publisher.publish_draft(
                "pubjob-" + str(job["id"]) + "-publish",
                job["blog_id"],
                str(job["remote_post_id"]),
                source_draft_key="pubjob-" + str(job["id"]) + "-draft",
            )
        if result.get("status") != "LIVE" or not result.get("readback_verified"):
            raise GoogleFailure("published_readback_mismatch")
        with connection() as conn:
            conn.execute(
                "UPDATE publishing_jobs SET status='succeeded',publication_state='published',live_stage='published',remote_post_id=%s,lease_until=NULL,updated_at=now() WHERE id=%s",
                (result['post_id'],job["id"]),
            )
            conn.execute(
                """INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,remote_url,published_at,remote_status,remote_verified_at)
                VALUES(%s,%s,%s,%s,%s,%s,'LIVE',now())""",
                (
                    job["id"],
                    job["blog_id"],
                    job["content_version_id"],
                    result["post_id"],
                    result.get("url"),
                    result['published_at'],
                ),
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES('automation.auto_job.published',%s)",
                (Jsonb({"job_id": str(job["id"]), "post_id": str(result["post_id"])}),),
            )
        return {"job_id": str(job["id"]), "status": "published"}
    except WriteIntervalWait as exc:
        with connection() as conn:
            conn.execute(
                "UPDATE publishing_jobs SET status='queued',available_at=%s,lease_until=NULL WHERE id=%s",
                (exc.available_at, job["id"]),
            )
        return {"job_id": str(job["id"]), "status": "interval_wait"}
    except GoogleFailure as exc:
        with connection() as conn:
            conn.execute(
                "UPDATE publishing_jobs SET status='uncertain',publication_state='publication_blocked',lease_until=NULL,last_error_category=%s,updated_at=now() WHERE id=%s",
                (exc.category, job["id"]),
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES('automation.auto_job.held',%s)",
                (
                    Jsonb(
                        {"job_id": str(job["id"]), "reason": exc.category, "automatic_retry": False}
                    ),
                ),
            )
        return {"job_id": str(job["id"]), "status": "uncertain", "reason": exc.category}
