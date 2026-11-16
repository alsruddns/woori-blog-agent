"""Read-only eligibility review for pre-job publication failures."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import automation_controls
from .db import connection
from .publication_daily import (
    GLOBAL_DAILY_PUBLISH_LIMIT,
    KST,
    kst_day_bounds,
    verified_live_by_language,
)


def recheck(targets: list[dict[str, Any]], *, actor: str, reason: str) -> dict[str, Any]:
    """Re-evaluate selected failures without creating a Job or contacting Blogger."""
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, UUID, UUID, UUID]] = set()
    with connection() as conn:
        lock = conn.execute("SELECT pg_try_advisory_xact_lock(20261102,103) acquired").fetchone()
        if not lock or not lock["acquired"]:
            raise HTTPException(409, "A Blogger write is active; retry the read-only review after it finishes")
        controls = automation_controls.read(conn, lock=True)
        mode = conn.execute(
            "SELECT configured_mode,blogger_write_mode,blogger_api_restricted,emergency_stopped,operations_auto_approved "
            "FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
        ).fetchone()
        start, end = kst_day_bounds(datetime.now(KST).date())
        live_counts = verified_live_by_language(conn, start, end)
        today_live_count = sum(live_counts.values())
        scheduled_policy = conn.execute(
            "SELECT action,approved_blog_ids FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        for target in targets:
            key = (int(target["event_id"]), UUID(str(target["import_id"])),
                   UUID(str(target["content_version_id"])), UUID(str(target["blog_id"])))
            if key in seen:
                continue
            seen.add(key)
            event_id, import_id, version_id, blog_id = key
            row = conn.execute(
                """WITH latest AS (
                    SELECT DISTINCT ON(payload->>'import_id',payload->>'content_version_id',payload->>'blog_record_id')
                      id,event_type,payload FROM audit_events
                    WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
                      AND payload->>'import_id'=%s AND payload->>'content_version_id'=%s
                      AND payload->>'blog_record_id'=%s
                    ORDER BY payload->>'import_id',payload->>'content_version_id',payload->>'blog_record_id',id DESC
                  )
                  SELECT latest.id AS latest_event_id,latest.event_type,latest.payload,
                    i.generation_method,i.language_code,i.id AS import_id,
                    v.id AS content_version_id,v.group_id,v.localization_id,v.version,
                    b.id AS blog_id,b.blog_id AS blogger_blog_id,b.active AS blog_active,
                    l.active AS language_active,d.status AS discard_status,
                    current_v.id AS current_version_id,
                    evaluation.created_at AS evaluation_at,evaluation.status AS evaluation_status,
                    evaluation.publish_ready,
                    jobs.job_count,jobs.latest_status,
                    remote.remote_status,remote.remote_post_id,remote.remote_verified_at
                  FROM latest
                  LEFT JOIN external_content_imports i ON i.id=%s
                  LEFT JOIN content_versions v ON v.id=%s
                  LEFT JOIN blogger_blogs b ON b.id=%s
                  LEFT JOIN languages l ON l.code=i.language_code
                  LEFT JOIN manuscript_discards d ON d.group_id=v.group_id AND d.blog_id=b.id
                  LEFT JOIN LATERAL (SELECT cv.id FROM content_versions cv
                    WHERE cv.group_id=v.group_id AND cv.localization_id IS NOT DISTINCT FROM v.localization_id
                    ORDER BY cv.version DESC,cv.created_at DESC,cv.id DESC LIMIT 1) current_v ON true
                  LEFT JOIN LATERAL (SELECT created_at,status,publish_ready FROM article_quality_evaluations
                    WHERE content_version_id=current_v.id ORDER BY created_at DESC,id DESC LIMIT 1) evaluation ON true
                  LEFT JOIN LATERAL (SELECT count(*)::int AS job_count,
                      (array_agg(j.status ORDER BY j.updated_at DESC,j.id DESC))[1] AS latest_status
                    FROM publishing_jobs j WHERE j.blog_id=b.id AND j.content_version_id=v.id
                      AND j.adapter_type='blogger_live' AND NOT j.simulation_only) jobs ON true
                  LEFT JOIN LATERAL (SELECT r.remote_status,r.remote_post_id,r.remote_verified_at
                    FROM publishing_records r JOIN content_versions rv ON rv.id=r.content_version_id
                    WHERE r.blog_id=b.id AND rv.group_id=v.group_id
                    ORDER BY r.published_at DESC NULLS LAST,r.id DESC LIMIT 1) remote ON true""",
                (str(import_id), str(version_id), str(blog_id), import_id, version_id, blog_id),
            ).fetchone()
            blockers: list[str] = []
            cause = "unknown"
            if not row or row["latest_event_id"] != event_id or row["event_type"] != "publication.auto_failure.recorded":
                blockers.append("failure_record_superseded_or_missing")
            else:
                payload = row["payload"] or {}
                codes = set(payload.get("reason_codes") or [])
                if payload.get("failure_reason_code"):
                    codes.add(str(payload["failure_reason_code"]))
                cause = str(payload.get("failure_reason_code") or "unknown")
                if row["discard_status"] == "discarded":
                    blockers.append("manuscript_discarded_restore_before_review")
                if not row["blog_active"]:
                    blockers.append("blog_inactive")
                if not row["language_active"]:
                    blockers.append("language_inactive")
                if not row["import_id"] or not conn.execute(
                    "SELECT 1 FROM external_content_import_content_links WHERE import_id=%s AND content_version_id=%s",
                    (import_id, version_id),
                ).fetchone():
                    blockers.append("import_version_link_missing")
                if row["current_version_id"] != version_id:
                    blockers.append("content_version_is_not_current")
                if row["evaluation_at"] is None or row["publish_ready"] is not True:
                    blockers.append("quality_evaluation_required")
                if row["job_count"]:
                    blockers.append("existing_job_requires_reconciliation")
                if row["remote_status"] == "LIVE" and row["remote_verified_at"]:
                    blockers.append("verified_live_publication_exists")
                elif row["remote_status"] in {"LIVE", "DRAFT", "unknown"}:
                    blockers.append("remote_publication_status_requires_review")
                if "remote_duplicate_found" in codes:
                    blockers.append("remote_duplicate_found")
                if "remote_duplicate_check_unknown" in codes:
                    blockers.append("remote_duplicate_check_required_before_request")
                if codes & {"source_live_verification_missing", "claim_source_verification_unavailable"}:
                    blockers.append("source_verification_required")
                if not controls["manual_publishing_enabled"]:
                    blockers.append("manual_publishing_disabled")
                if today_live_count >= controls.get("global_daily_live_publish_limit", GLOBAL_DAILY_PUBLISH_LIMIT):
                    blockers.append("global_daily_live_limit_reached")
                if mode and mode["emergency_stopped"]:
                    blockers.append("emergency_stop_enabled")
                if mode and mode["blogger_api_restricted"]:
                    blockers.append("blogger_api_restricted")
            current_automatic_blockers: list[str] = []
            scheduled_origin = bool(row and row["generation_method"] == "chatgpt_scheduled_export")
            trends_origin = bool(row and row["generation_method"] == "codex_trends_export")
            if not scheduled_origin and not controls["automatic_publication_operator_approved"]:
                current_automatic_blockers.append("automatic_publication_operator_approval_off")
            if not scheduled_origin and not controls["auto_publishing_enabled"]:
                current_automatic_blockers.append("global_auto_publication_off")
            if scheduled_origin:
                if not controls["scheduled_auto_publishing_enabled"]:
                    current_automatic_blockers.append("scheduled_auto_publication_off")
                approved_blogs = {str(value) for value in (scheduled_policy["approved_blog_ids"] or [])} if scheduled_policy else set()
                if not scheduled_policy or scheduled_policy["action"] != "enabled" or str(blog_id) not in approved_blogs:
                    current_automatic_blockers.append("scheduled_auto_policy_not_approved")
            if trends_origin and not controls["trends_auto_publishing_enabled"]:
                current_automatic_blockers.append("trends_auto_publication_off")
            if not scheduled_origin and mode and not mode["operations_auto_approved"]:
                current_automatic_blockers.append("operations_auto_approved_false")
            if not scheduled_origin and mode and mode["configured_mode"] != "auto":
                current_automatic_blockers.append("global_publication_mode_manual")
            if mode and mode["emergency_stopped"]:
                current_automatic_blockers.append("emergency_stop_enabled")
            result = {
                "event_id": event_id, "import_id": str(import_id),
                "content_version_id": str(version_id), "blog_id": str(blog_id),
                "root_cause": cause,
                "status": "blocked" if blockers else "local_checks_passed",
                "blockers": list(dict.fromkeys(blockers)),
                "automatic_publication_blockers": list(dict.fromkeys(current_automatic_blockers)),
                "evaluation_at": row["evaluation_at"] if row else None,
                "evaluation_status": row["evaluation_status"] if row else None,
                "publish_ready": row["publish_ready"] if row else False,
                "existing_job_count": row["job_count"] if row else 0,
                "remote_status": row["remote_status"] if row else None,
                "remote_post_id": row["remote_post_id"] if row else None,
                "manual_request_preflight_required": not blockers,
                "next_action": "restore_before_recheck" if row and row["discard_status"] == "discarded"
                    else "manual_exact_version_preflight" if not blockers else "review_blockers",
            }
            results.append(result)
            conn.execute(
                """INSERT INTO audit_events(event_type,payload) VALUES('publication.pre_job_failure.rechecked',%s)""",
                (Jsonb({**result, "actor": actor.strip(), "reason": reason.strip(),
                        "occurred_at": datetime.now(UTC).isoformat(), "job_created": False,
                        "blogger_write_performed": False, "settings_revision": controls["revision"]}),),
            )
        return {
            "results": results, "settings_revision": controls["revision"],
            "today_live_count_kst": today_live_count,
            "daily_live_limit": controls.get("global_daily_live_publish_limit", GLOBAL_DAILY_PUBLISH_LIMIT),
            "global_publish_min_interval_minutes": controls.get("global_publish_min_interval_minutes"),
            "job_created": False, "blogger_write_performed": False,
        }


def history_action(targets: list[dict[str, Any]], *, actor: str, reason: str, action: str) -> dict[str, Any]:
    """Archive or restore only the failure-history view; never change manuscript discard state."""
    if action not in {"archive", "restore"}:
        raise HTTPException(422, "Unsupported history action")
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, UUID, UUID, UUID]] = set()
    with connection() as conn:
        for target in targets:
            key = (int(target["event_id"]), UUID(str(target["import_id"])),
                   UUID(str(target["content_version_id"])), UUID(str(target["blog_id"])))
            if key in seen:
                continue
            seen.add(key)
            event_id, import_id, version_id, blog_id = key
            latest = conn.execute(
                """SELECT id,event_type FROM audit_events
                   WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
                     AND payload->>'import_id'=%s AND payload->>'content_version_id'=%s
                     AND payload->>'blog_record_id'=%s
                   ORDER BY id DESC LIMIT 1""",
                (str(import_id), str(version_id), str(blog_id)),
            ).fetchone()
            if not latest or latest["id"] != event_id or latest["event_type"] != "publication.auto_failure.recorded":
                results.append({"event_id": event_id, "status": "failure_record_superseded_or_missing"})
                continue
            last_history = conn.execute(
                """SELECT event_type FROM audit_events WHERE event_type IN
                     ('publication.pre_job_failure.archived','publication.pre_job_failure.restored')
                     AND payload->>'failure_event_id'=%s ORDER BY id DESC LIMIT 1""",
                (str(event_id),),
            ).fetchone()
            currently_archived = bool(last_history and last_history["event_type"] == "publication.pre_job_failure.archived")
            if (action == "archive" and currently_archived) or (action == "restore" and not currently_archived):
                results.append({"event_id": event_id, "status": "already_in_requested_state"})
                continue
            payload = {
                "failure_event_id": event_id, "import_id": str(import_id),
                "content_version_id": str(version_id), "blog_record_id": str(blog_id),
                "actor": actor.strip(), "reason": reason.strip(),
                "occurred_at": datetime.now(UTC).isoformat(),
                "publication_job_created": False, "blogger_write_performed": False,
            }
            event_type = "publication.pre_job_failure.archived" if action == "archive" else "publication.pre_job_failure.restored"
            inserted = conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES(%s,%s) RETURNING id",
                (event_type, Jsonb(payload)),
            ).fetchone()
            if not inserted:
                raise RuntimeError("Failure-history audit event was not recorded")
            discard = conn.execute(
                """SELECT d.status FROM content_versions v JOIN manuscript_discards d ON d.group_id=v.group_id
                   WHERE v.id=%s AND d.blog_id=%s LIMIT 1""", (str(version_id), str(blog_id),)
            ).fetchone()
            results.append({"event_id": event_id, "history_event_id": inserted["id"],
                            "status": "archived" if action == "archive" else "restored",
                            "manuscript_still_discarded": bool(discard and discard["status"] == "discarded"),
                            "publication_job_created": False, "blogger_write_performed": False})
        return {"results": results, "action": action,
                "publication_job_created": False, "blogger_write_performed": False}
