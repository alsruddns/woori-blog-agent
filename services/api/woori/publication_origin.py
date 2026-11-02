"""Conservative origin lineage and the common automatic publication decision."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

ROUTES = {"google_trends": "trends", "scheduled": "scheduled"}


def classify(conn: Any, version_id: Any, blog_id: Any, *, verify_execution_receipt: bool = True) -> dict[str, Any]:
    unknown = {
        "kind": "unknown",
        "content_version_id": str(version_id),
        "target_blog_id": str(blog_id),
        "reason": "origin_lineage_missing_or_ambiguous",
    }
    links = conn.execute(
        """SELECT i.id AS import_id,i.generation_method,i.language_code,i.received_at,
        iv.id AS import_version_id,b.blog_id AS blogger_id,b.language_code AS blog_language
        FROM external_content_import_content_links l JOIN external_content_imports i ON i.id=l.import_id
        JOIN external_content_import_versions iv ON iv.id=l.import_version_id AND iv.import_id=i.id
        JOIN blogger_blogs b ON b.id=%s WHERE l.content_version_id=%s""",
        (blog_id, version_id),
    ).fetchall()
    if len(links) != 1:
        return unknown
    link = links[0]
    base = {
        **unknown,
        "import_id": str(link["import_id"]),
        "import_version_id": str(link["import_version_id"]),
    }
    if link["language_code"] != link["blog_language"]:
        return base | {"reason": "origin_target_language_mismatch"}
    method = link["generation_method"]
    if method == "manual_codex_import":
        return base | {
            "kind": "manual",
            "reason": "manual_import_not_automatic",
            "completed_at": link["received_at"],
        }
    if method == "codex_trends_export":
        jobs = conn.execute(
            """SELECT j.id,j.completed_at,j.trend_request_id FROM codex_authoring_jobs j
            JOIN trend_generation_requests q ON q.id=j.trend_request_id AND q.authoring_job_id=j.id
            JOIN external_content_import_content_links initial ON initial.import_id=j.import_id
                AND initial.content_version_id=j.content_version_id
            WHERE j.import_id=%s AND j.blog_id=%s AND j.job_type='google_trends'
             AND j.state='imported_review' AND q.state='imported' AND j.completed_at IS NOT NULL
             AND EXISTS(SELECT 1 FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id WHERE m.topic_id=q.topic_id)
            GROUP BY j.id""",
            (link["import_id"], blog_id),
        ).fetchall()
        if len(jobs) != 1:
            return base
        return base | {
            "kind": "google_trends",
            "reason": "linked_trends_job_import_completed",
            "authoring_job_id": str(jobs[0]["id"]),
            "trend_request_id": str(jobs[0]["trend_request_id"]),
            "completed_at": max(link["received_at"], jobs[0]["completed_at"]),
        }
    if method != "chatgpt_scheduled_export":
        return base
    origins = conn.execute(
        """SELECT id,payload,created_at FROM audit_events
        WHERE event_type='content.import.scheduled_origin_recorded' AND payload->>'import_id'=%s""",
        (str(link["import_id"]),),
    ).fetchall()
    if len(origins) != 1:
        return base
    origin = origins[0]["payload"]
    required = (
        "automation_id",
        "scheduled_slot",
        "occurrence_id",
        "occurrence_id_source",
        "target_blog_id",
    )
    if any(not origin.get(k) for k in required) or origin["target_blog_id"] != link["blogger_id"]:
        return base | {"reason": "scheduled_origin_fields_or_target_invalid"}
    try:
        from .scheduled_occurrence import validate_occurrence_metadata

        validate_occurrence_metadata(
            occurrence_id=origin["occurrence_id"],
            occurrence_id_source=origin["occurrence_id_source"],
            scheduler_occurrence_id=origin.get("scheduler_occurrence_id"),
            automation_id=origin["automation_id"],
            scheduled_slot=datetime.fromisoformat(origin["scheduled_slot"]),
        )
        if origin["occurrence_id_source"] not in {"scheduler_issued", "project_derived_kst_slot"}:
            return base
        if verify_execution_receipt:
            from .scheduled_execution_receipts import verify

            if not verify(origin):
                return base | {"reason": "scheduled_execution_receipt_unverified"}
    except (ValueError, TypeError, KeyError):
        return base
    return base | {
        "kind": "scheduled",
        "reason": "verified_scheduled_execution_and_import" if verify_execution_receipt else "recorded_scheduled_origin_and_import",
        "automation_id": origin["automation_id"],
        "scheduled_slot": origin["scheduled_slot"],
        "occurrence_id": origin["occurrence_id"],
        "occurrence_id_source": origin["occurrence_id_source"],
        "scheduler_occurrence_id": origin.get("scheduler_occurrence_id"),
        "completed_at": max(link["received_at"], origins[0]["created_at"]),
    }


def classify_display_many(conn: Any, identities: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Resolve list badges from stored lineage in batches; never grants publication rights."""
    if not identities:
        return {}
    versions = list({version for version, _ in identities})
    blogs = list({blog for _, blog in identities})
    linked = conn.execute(
        """SELECT requested.id AS requested_version,linked.id AS linked_version,
          i.id AS import_id,i.generation_method,i.language_code
        FROM content_versions requested JOIN content_versions linked
          ON linked.group_id=requested.group_id
          AND linked.localization_id IS NOT DISTINCT FROM requested.localization_id
        JOIN external_content_import_content_links l ON l.content_version_id=linked.id
        JOIN external_content_imports i ON i.id=l.import_id
        WHERE requested.id=ANY(%s::uuid[])
        ORDER BY requested.id,(linked.id=requested.id) DESC,linked.version DESC,linked.id DESC""",
        (versions,),
    ).fetchall()
    by_version: dict[str, dict[str, Any]] = {}
    ambiguous_versions: set[str] = set()
    for row in linked:
        requested = str(row["requested_version"])
        first = by_version.setdefault(requested, dict(row))
        if first["linked_version"] == row["linked_version"] and first["import_id"] != row["import_id"]:
            ambiguous_versions.add(requested)
    blog_rows = conn.execute(
        "SELECT id,blog_id,language_code FROM blogger_blogs WHERE id=ANY(%s::uuid[])", (blogs,)
    ).fetchall()
    by_blog = {str(row["id"]): row for row in blog_rows}
    import_ids = list({str(row["import_id"]) for row in by_version.values()})
    scheduled = conn.execute(
        """SELECT payload FROM audit_events WHERE event_type='content.import.scheduled_origin_recorded'
        AND payload->>'import_id'=ANY(%s::text[])""", (import_ids,),
    ).fetchall() if import_ids else []
    scheduled_by_import: dict[str, list[dict[str, Any]]] = {}
    for row in scheduled:
        scheduled_by_import.setdefault(str(row["payload"].get("import_id")), []).append(row["payload"])
    trend_rows = conn.execute(
        """SELECT j.import_id,j.blog_id,j.id,j.trend_request_id
        FROM codex_authoring_jobs j JOIN trend_generation_requests q
          ON q.id=j.trend_request_id AND q.authoring_job_id=j.id
        WHERE j.import_id=ANY(%s::uuid[]) AND j.job_type='google_trends'
          AND j.state='imported_review' AND q.state='imported' AND j.completed_at IS NOT NULL
          AND EXISTS(SELECT 1 FROM trend_topic_memberships m JOIN trend_observations o
            ON o.id=m.observation_id WHERE m.topic_id=q.topic_id)""",
        (import_ids,),
    ).fetchall() if import_ids else []
    trends_by_import: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in trend_rows:
        trends_by_import.setdefault((str(row["import_id"]), str(row["blog_id"])), []).append(dict(row))
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for version, blog in identities:
        result: dict[str, Any] = {"kind": "unknown", "reason": "origin_lineage_missing_or_ambiguous"}
        import_row, target = by_version.get(version), by_blog.get(blog)
        if version not in ambiguous_versions and import_row and target and import_row["language_code"] == target["language_code"]:
            method, import_id = import_row["generation_method"], str(import_row["import_id"])
            if method == "manual_codex_import":
                result = {"kind": "manual", "reason": "linked_manual_import", "import_id": import_id}
            elif method == "codex_trends_export":
                jobs = trends_by_import.get((import_id, blog), [])
                if len(jobs) == 1:
                    result = {"kind": "google_trends", "reason": "linked_trends_job_import_completed",
                              "import_id": import_id, "authoring_job_id": str(jobs[0]["id"]),
                              "trend_request_id": str(jobs[0]["trend_request_id"])}
            elif method == "chatgpt_scheduled_export":
                origins = scheduled_by_import.get(import_id, [])
                if len(origins) == 1:
                    origin = origins[0]
                    try:
                        from .scheduled_occurrence import validate_occurrence_metadata

                        if origin.get("target_blog_id") != target["blog_id"]:
                            raise ValueError("target mismatch")
                        validate_occurrence_metadata(
                            occurrence_id=origin["occurrence_id"],
                            occurrence_id_source=origin["occurrence_id_source"],
                            scheduler_occurrence_id=origin.get("scheduler_occurrence_id"),
                            automation_id=origin["automation_id"],
                            scheduled_slot=datetime.fromisoformat(origin["scheduled_slot"]),
                        )
                        result = {"kind": "scheduled", "reason": "recorded_scheduled_origin_and_import",
                                  "import_id": import_id, "automation_id": origin["automation_id"],
                                  "scheduled_slot": origin["scheduled_slot"], "occurrence_id": origin["occurrence_id"]}
                    except (ValueError, TypeError, KeyError):
                        pass
        results[(version, blog)] = result
    return results


def decide(
    settings: dict[str, Any],
    origin: dict[str, Any],
    target_blog: Any,
    job: dict[str, Any],
    content_version: Any,
    *,
    emergency_stop: bool | None = None,
) -> dict[str, Any]:
    reasons = []
    if not settings.get("auto_publishing_enabled"):
        reasons.append("global_auto_publish_disabled")
    kind = origin.get("kind", "unknown")
    route = ROUTES.get(kind)
    if not route:
        reasons.append(
            "manual_manuscript_excluded" if kind == "manual" else "unknown_manuscript_origin"
        )
    elif not settings.get(route + "_auto_publishing_enabled"):
        reasons.append(route + "_auto_publish_disabled")
    if settings.get("emergency_stop", True) if emergency_stop is None else emergency_stop:
        reasons.append("emergency_stop_enabled")
    if settings.get("blogger_api_restricted", True):
        reasons.append("blogger_api_restricted")
    if str(target_blog) not in {str(x) for x in settings.get("auto_blog_ids", [])}:
        reasons.append("automatic_target_not_approved")
    if str(origin.get("content_version_id")) != str(content_version) or str(
        origin.get("target_blog_id")
    ) != str(target_blog):
        reasons.append("origin_content_version_or_target_mismatch")
    if not job.get("epoch") or str(job.get("epoch")) != str(settings.get("auto_epoch")):
        reasons.append("automatic_grant_expired")
    if job.get("publication_mode") != settings.get("auto_mode"):
        reasons.append("automatic_mode_mismatch")
    if route:
        if not job.get("source_epoch") or str(job.get("source_epoch")) != str(
            settings.get(route + "_auto_epoch")
        ):
            reasons.append("origin_grant_expired")
        if (
            job.get("manuscript_origin") != kind
            or str(job.get("origin_import_id")) != str(origin.get("import_id"))
            or str(job.get("origin_content_version_id")) != str(content_version)
        ):
            reasons.append("origin_grant_binding_mismatch")
        completed = origin.get("completed_at")
        cutoffs = [settings.get("auto_enabled_at"), settings.get(route + "_auto_enabled_at")]
        if (
            not isinstance(completed, datetime)
            or completed.tzinfo is None
            or any(
                not isinstance(t, datetime) or t.tzinfo is None or completed <= t for t in cutoffs
            )
        ):
            reasons.append("origin_predates_activation")
    if job.get("quality_ready") is False:
        reasons.append("quality_review_required")
    if job.get("duplicate") is True:
        reasons.append("duplicate_publication")
    return {"allowed": not reasons, "reasons": reasons, "origin": kind}


def record_block(
    conn: Any, version_id: Any, blog_id: Any, revision: int, result: dict[str, Any], stage: str
) -> None:
    key = hashlib.sha256(
        json.dumps(
            [str(version_id), str(blog_id), revision, result["reasons"], stage], sort_keys=True
        ).encode()
    ).hexdigest()
    if conn.execute(
        "SELECT 1 FROM audit_events WHERE event_type='automation.origin_publication.blocked' AND payload->>'decision_key'=%s LIMIT 1",
        (key,),
    ).fetchone():
        return
    conn.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES('automation.origin_publication.blocked',%s)",
        (
            Jsonb(
                {
                    "decision_key": key,
                    "content_version_id": str(version_id),
                    "blog_id": str(blog_id),
                    "revision": revision,
                    "stage": stage,
                    **result,
                    "blogger_write_performed": False,
                }
            ),
        ),
    )
