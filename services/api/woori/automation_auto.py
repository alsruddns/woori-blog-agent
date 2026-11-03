"""New-epoch, reviewed-version automatic dispatch; historical queues are untouched."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from . import automation_controls as controls
from . import publication_origin
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
    from .publication_discards import discarded

    if discarded(conn, version, blog):
        return None, {}, ["manuscript_discarded"]
    # Admission is checked separately at the wire; avoid recursively entering
    # AUTO_JOB while rechecking content safety immediately before HTTP.
    from . import publication_origin

    origin = publication_origin.classify(conn, version, blog)
    if origin["kind"] == "scheduled":
        from .publication_worker import _scheduled_eligibility

        imported = conn.execute(
            """SELECT i.*,iv.id AS import_version_id,iv.content_sha256 AS import_hash,
            l.content_version_id FROM external_content_imports i
            JOIN external_content_import_versions iv ON iv.import_id=i.id
            JOIN external_content_import_content_links l ON l.import_id=i.id AND l.import_version_id=iv.id
            WHERE l.content_version_id=%s AND i.id=%s
              AND iv.version_number=(SELECT max(newest.version_number)
                FROM external_content_import_versions newest WHERE newest.import_id=i.id)""",
            (version, origin["import_id"]),
        ).fetchone()
        from .external_policy import _scheduled_publication_approval

        if not imported or _scheduled_publication_approval(str(blog)) is None:
            reasons = ["scheduled_import_or_policy_unavailable"]
        else:
            target = conn.execute(
                """SELECT b.*,g.status AS oauth_status FROM blogger_blogs b
                LEFT JOIN google_connections g ON g.id=b.oauth_connection_id WHERE b.id=%s""",
                (blog,),
            ).fetchone()
            reasons = (
                _scheduled_eligibility(
                    conn, imported,
                    {"id": imported["import_version_id"], "content_version_id": version},
                    target,
                )["reasons"]
                if target else ["scheduled_target_unavailable"]
            )
    else:
        reasons = publications._assess(row, check_write_policy=False)["reasons"]
    snapshot = publications._manual_publication_snapshot(conn, dict(row))
    reasons.extend(snapshot["blockers"])
    from .editorial_quality import VERSION as QUALITY_VERSION

    report = conn.execute(
        """SELECT result FROM editorial_quality_reports WHERE content_version_id=%s
        AND engine_version=%s AND stage='static' AND status='completed' ORDER BY created_at DESC LIMIT 1""",
        (version, QUALITY_VERSION),
    ).fetchone()
    if not report or report["result"].get("checks", {}).get("safe_html") is False:
        reasons.append("quality_review_required")
    newest = conn.execute(
        "SELECT id FROM content_versions WHERE group_id=%s AND localization_id IS NOT DISTINCT FROM %s ORDER BY version DESC,created_at DESC LIMIT 1",
        (row["group_id"], row["localization_id"]),
    ).fetchone()
    if not newest or newest["id"] != version:
        reasons.append("stale_version")
    return dict(row), snapshot, sorted(set(reasons))


def scheduled_daily_available(conn: Any, blog_id: UUID) -> bool:
    """Use the existing scoped Scheduled Auto KST daily ceiling."""
    policy = conn.execute(
        """SELECT action,daily_limit FROM scheduled_publication_policy_events
        ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    daily = conn.execute(
        """SELECT count(*)::int AS n FROM publishing_jobs
        WHERE publication_lane='scheduled_auto' AND blog_id=%s
          AND status IN ('queued','running','uncertain','succeeded')
          AND scheduled_at >= date_trunc('day',now() AT TIME ZONE 'Asia/Seoul')
            AT TIME ZONE 'Asia/Seoul'""",
        (blog_id,),
    ).fetchone()
    return bool(policy and policy["action"] == "enabled" and daily is not None
                and int(daily["n"]) < int(policy["daily_limit"]))


def enqueue(conn: Any, state: dict[str, Any], *, origin_filter: str | None = None) -> int:
    if (
        not state["auto_publishing_enabled"]
        or not state["automatic_publication_operator_approved"]
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
          AND NOT EXISTS(SELECT 1 FROM manuscript_discards d WHERE d.group_id=v.group_id
            AND d.blog_id=b.id AND d.status='discarded')
          AND NOT EXISTS(SELECT 1 FROM publishing_jobs j WHERE j.blog_id=b.id AND j.content_version_id=v.id AND NOT j.simulation_only)
        ORDER BY v.created_at,v.id""",
        (state["auto_blog_ids"], state["auto_enabled_at"]),
    ).fetchall()
    created = 0
    for item in rows:
        if created >= 10:
            break
        origin = publication_origin.classify(conn, item["id"], item["blog_id"])
        if origin_filter is not None and origin["kind"] != origin_filter:
            continue
        route = publication_origin.ROUTES.get(origin["kind"])
        grant = {
            "epoch": state["auto_epoch"],
            "publication_mode": state["auto_mode"],
            "source_epoch": state.get(str(route) + "_auto_epoch"),
            "manuscript_origin": origin["kind"],
            "origin_import_id": origin.get("import_id"),
            "origin_content_version_id": item["id"],
        }
        decision = publication_origin.decide(state, origin, item["blog_id"], grant, item["id"])
        if not decision["allowed"]:
            publication_origin.record_block(
                conn, item["id"], item["blog_id"], state["revision"], decision, "enqueue"
            )
            continue
        # Preserve the scoped Scheduled Auto daily ceiling in the new lane.
        if origin["kind"] == "scheduled" and not scheduled_daily_available(conn, item["blog_id"]):
            publication_origin.record_block(
                conn, item["id"], item["blog_id"], state["revision"],
                {"allowed": False, "reasons": ["scheduled_daily_publication_limit_or_policy_unavailable"], "origin": "scheduled"},
                "enqueue",
            )
            continue
        row, _snapshot, reasons = readiness(conn, item["id"], item["blog_id"])
        if reasons or row is None:
            continue
        job_lane = "trends_auto" if origin["kind"] == "google_trends" else "scheduled_auto"
        job = conn.execute(
            """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
            scheduled_at,status,publication_state,adapter_type,simulation_only,block_reasons,oauth_connection_id,
            live_stage,publication_lane,publication_mode)
            VALUES(%s,%s,%s,%s,now(),'queued','publication_queued','blogger_live',false,'[]',%s,'draft_needed',%s,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
            (
                row["policy_id"],
                item["blog_id"],
                item["id"],
                f"p103-{item['id']}-{item['blog_id']}",
                row["oauth_connection_id"],
                job_lane,
                state["auto_mode"],
            ),
        ).fetchone()
        if not job:
            continue
        conn.execute(
            """INSERT INTO automation_publication_grants(job_id,epoch,lane,publication_mode,manuscript_origin,
            source_epoch,origin_import_id,origin_content_version_id) VALUES(%s,%s,'auto',%s,%s,%s,%s,%s)""",
            (
                job["id"],
                state["auto_epoch"],
                state["auto_mode"],
                origin["kind"],
                grant["source_epoch"],
                origin["import_id"],
                item["id"],
            ),
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
                        "manuscript_origin": origin["kind"],
                        "import_id": origin["import_id"],
                    }
                ),
            ),
        )
        created += 1
    return created


def tick(*, publisher: Any = None, origin_filter: str | None = None) -> dict[str, Any] | None:
    from .blogger_writes import BloggerLivePublisher, WriteIntervalWait
    from .google_http import GoogleFailure
    from .publication_worker import save_verified_draft
    from .scheduled_duplicates import find_remote_duplicate

    if origin_filter not in {None, "scheduled", "google_trends"}:
        raise ValueError("invalid_publication_origin_filter")
    with connection() as conn:
        lock = conn.execute("SELECT pg_try_advisory_xact_lock(20261102,10301) acquired").fetchone()
        if not lock or not lock["acquired"]:
            return None
        state = controls.read(conn)
        enqueue(conn, state, origin_filter=origin_filter)
        if (
            not state["auto_publishing_enabled"]
            or state["emergency_stop"]
            or state["blogger_api_restricted"]
        ):
            return None
        job = conn.execute(
            """SELECT j.* FROM publishing_jobs j JOIN automation_publication_grants g ON g.job_id=j.id
            WHERE g.lane='auto' AND g.epoch=%s AND j.status='queued' AND j.available_at<=now()
              AND NOT EXISTS(SELECT 1 FROM content_versions v JOIN manuscript_discards d
                ON d.group_id=v.group_id AND d.blog_id=j.blog_id AND d.status='discarded'
                WHERE v.id=j.content_version_id)
              AND (%s::text IS NULL OR g.manuscript_origin=%s)
              AND ((g.manuscript_origin='google_trends' AND %s AND g.source_epoch=%s)
                   OR (g.manuscript_origin='scheduled' AND %s AND g.source_epoch=%s))
              AND j.scheduled_at<=now() ORDER BY CASE g.manuscript_origin WHEN 'scheduled' THEN 0 ELSE 1 END,
                CASE WHEN g.manuscript_origin='google_trends' THEN CASE
                  (SELECT language_code FROM blogger_blogs b WHERE b.id=j.blog_id)
                  WHEN 'en' THEN 0 WHEN 'ko' THEN 1 WHEN 'ja' THEN 2 WHEN 'zh-CN' THEN 3
                  WHEN 'de' THEN 4 WHEN 'pt-BR' THEN 5 WHEN 'vi' THEN 6 ELSE 7 END ELSE 0 END,
                j.scheduled_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (
                state["auto_epoch"],
                origin_filter,
                origin_filter,
                state["trends_auto_publishing_enabled"],
                state["trends_auto_epoch"],
                state["scheduled_auto_publishing_enabled"],
                state["scheduled_auto_epoch"],
            ),
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
                if job["publication_mode"] == "draft":
                    result = publisher.create_draft(
                        "pubjob-" + str(job["id"]) + "-draft",
                        job["blog_id"], snapshot["title"], snapshot["safe_html"],
                        snapshot["blogger_labels"],
                    )
                    return save_verified_draft(
                        job["id"], job["blog_id"], job["content_version_id"], result
                    )
                result = publisher.create_live(
                    "pubjob-" + str(job["id"]) + "-publish",
                    job["blog_id"], snapshot["title"], snapshot["safe_html"],
                    snapshot["blogger_labels"],
                )
            else:
                result = publisher.publish_draft(
                    "pubjob-" + str(job["id"]) + "-publish",
                    job["blog_id"], str(job["remote_post_id"]),
                    source_draft_key="pubjob-" + str(job["id"]) + "-draft",
                )
        if result.get("status") != "LIVE" or not result.get("readback_verified"):
            raise GoogleFailure("published_readback_mismatch")
        with connection() as conn:
            conn.execute(
                "UPDATE publishing_jobs SET status='succeeded',publication_state='published',live_stage='published',remote_post_id=%s,lease_until=NULL,updated_at=now() WHERE id=%s",
                (result["post_id"], job["id"]),
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
                    result["published_at"],
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
