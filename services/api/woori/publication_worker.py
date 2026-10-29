"""Lease-based Blogger publication worker with an explicit continuous service loop."""

from __future__ import annotations

import hashlib
import json
import signal
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
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
from .scheduled_duplicates import find_remote_duplicate
from .worker import (
    acquire_process_lock,
    consume_worker_stop_request,
    heartbeat,
    release_process_lock,
)


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


def _scheduled_eligibility(conn: Any, imported: Any, version: Any, blog: Any) -> list[str]:
    """Require durable source, rights and claim-review evidence for scheduled exports.

    This deliberately does not consult or mutate publish_ready/human publication
    approvals. Style/SEO recommendations are warnings; evidence, rights, safe
    HTML, identity, target and duplicate checks remain hard gates.
    """
    reasons: list[str] = []
    if imported["generation_method"] != "chatgpt_scheduled_export":
        reasons.append("not_a_scheduled_export")
    assessment = conn.execute(
        """SELECT machine_passed,safe_html,html_sha256,seo_checks FROM external_content_import_assessments
        WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1""",
        (imported["id"], version["id"]),
    ).fetchone()
    if not assessment or not assessment["machine_passed"] or not assessment["safe_html"]:
        reasons.append("scheduled_machine_or_html_gate_not_passed")
    claims = imported["claims"] or []
    sources = imported["sources"] or []
    source_by_id = {str(source.get("source_id")): source for source in sources}
    if not claims or any(
        claim.get("verification_status") not in {"source_span_verified", "corroborated"}
        or not set(claim.get("source_ids") or []).issubset(source_by_id)
        for claim in claims
    ):
        reasons.append("claim_evidence_incomplete")
    if not sources or any(
        source.get("rights_status") not in {"public_domain", "open_license", "permission_confirmed"}
        or not str(source.get("rights_note") or "").strip()
        for source in sources
    ):
        reasons.append("source_rights_not_cleared")
    verified = conn.execute(
        """SELECT DISTINCT ON (payload->>'source_id') payload FROM audit_events
        WHERE event_type='research.source.live_document_verified' AND payload->>'import_id'=%s
        ORDER BY payload->>'source_id',id DESC""", (str(imported["id"]),)
    ).fetchall()
    verified_by_id = {str(row["payload"].get("source_id")): row["payload"] for row in verified}
    for source_id, source in source_by_id.items():
        proof = verified_by_id.get(source_id)
        proof_url = (proof or {}).get("source_url") or (proof or {}).get("url")
        excerpts = (proof or {}).get("verified_claim_evidence", [])
        if (not proof or proof.get("http_status") != 200 or proof_url != str(source.get("url"))
                or not isinstance(excerpts, list) or not excerpts):
            reasons.append("source_live_verification_missing")
            break
    for claim in claims:
        evidence = str(claim.get("evidence_excerpt") or "").strip()
        attached = [verified_by_id.get(str(source_id), {}) for source_id in claim.get("source_ids", [])]
        if not evidence or not any(
            isinstance(item.get("verified_claim_evidence"), list)
            and any(evidence in str(span) for span in item["verified_claim_evidence"])
            for item in attached
        ):
            reasons.append("claim_span_not_found_in_live_source_evidence")
            break
    review = conn.execute(
        """SELECT claims_checked,rights_reviewed FROM external_content_import_review_events
        WHERE import_id=%s AND version_id=%s ORDER BY created_at DESC,id DESC LIMIT 1""",
        (imported["id"], version["id"]),
    ).fetchone()
    if not review or not review["claims_checked"]:
        reasons.append("claim_review_evidence_missing")
    if not review or not review["rights_reviewed"]:
        reasons.append("rights_review_evidence_missing")
    origin = conn.execute(
        """SELECT payload FROM audit_events WHERE event_type='content.import.scheduled_origin_recorded'
        AND payload->>'import_id'=%s ORDER BY id DESC LIMIT 1""", (str(imported["id"]),)
    ).fetchone()
    if (not origin or origin["payload"].get("target_blog_id") != str(blog["blog_id"])
            or origin["payload"].get("target_language_code") != str(blog["language_code"])):
        reasons.append("scheduled_origin_target_mismatch")
    if not blog["active"] or not blog["connection_verified_at"] or blog["oauth_status"] != "connected":
        reasons.append("blog_or_oauth_not_verified")
    if str(imported["language_code"]) != str(blog["language_code"]):
        reasons.append("scheduled_language_blog_mismatch")
    if str(imported["event_group_id"]):
        duplicate = conn.execute(
            """SELECT EXISTS(SELECT 1 FROM publishing_jobs j
            JOIN external_content_import_content_links l ON l.content_version_id=j.content_version_id
            JOIN external_content_imports i ON i.id=l.import_id
            WHERE j.blog_id=%s AND j.publication_lane='scheduled_auto'
              AND j.content_version_id<>%s AND i.event_group_id=%s
              AND j.status IN ('queued','running','uncertain','succeeded')) AS duplicate""",
            (blog["id"], version.get("content_version_id"), imported["event_group_id"]),
        ).fetchone()["duplicate"]
        if duplicate:
            reasons.append("same_event_already_queued_or_published")
    return list(dict.fromkeys(reasons))


def enqueue_scheduled_auto_jobs() -> dict[str, Any]:
    """Enqueue only evidence-reviewed scheduled exports inside the active policy scope."""
    created = 0
    held = 0
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('scheduled-auto-enqueue',0))")
        policy = conn.execute(
            """SELECT action,approved_blog_ids,daily_limit FROM scheduled_publication_policy_events
            ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        settings = conn.execute(
            "SELECT emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
        ).fetchone()
        if (not policy or policy.get("action") != "enabled" or not settings
                or settings.get("emergency_stopped")):
            return {"created": 0, "held": 0, "reason": "scheduled_auto_policy_off_or_stopped"}
        approved_blogs = {str(value) for value in policy["approved_blog_ids"]}
        prior_success = conn.execute(
            """SELECT EXISTS(SELECT 1 FROM publishing_jobs WHERE publication_lane='scheduled_auto'
            AND status='succeeded') AS value"""
        ).fetchone()["value"]
        rows = conn.execute(
            """SELECT i.*,v.id AS import_version_id,v.version_number,v.title AS import_title,
            v.body_markdown,v.blogger_labels,v.content_sha256 AS import_hash,
            link.content_version_id,cv.body AS content_body,b.id AS blog_record_id,b.blog_id,
            b.language_code AS blog_language,b.url,b.oauth_connection_id,b.active,b.connection_verified_at,
            g.status AS oauth_status
            FROM external_content_imports i
            JOIN external_content_import_versions v ON v.import_id=i.id
            JOIN external_content_import_content_links link
              ON link.import_id=i.id AND link.import_version_id=v.id
            JOIN content_versions cv ON cv.id=link.content_version_id
            JOIN blogger_blogs b ON b.language_code=i.language_code AND b.active
            JOIN google_connections g ON g.id=b.oauth_connection_id
            WHERE i.generation_method='chatgpt_scheduled_export'
              AND v.version_number=(SELECT max(v2.version_number) FROM external_content_import_versions v2 WHERE v2.import_id=i.id)
            ORDER BY i.received_at,i.id"""
        ).fetchall()
        for imported in rows:
            blog = dict(imported)
            if str(blog["blog_record_id"]) not in approved_blogs:
                continue
            if not prior_success:
                first = conn.execute(
                    """SELECT id FROM scheduled_first_publication_events
                    WHERE action='approved' AND blog_id=%s AND import_id=%s AND import_version_id=%s
                      AND content_version_id=%s AND body_sha256=%s AND NOT EXISTS (
                        SELECT 1 FROM scheduled_first_publication_events r WHERE r.action='revoked'
                        AND r.blog_id=scheduled_first_publication_events.blog_id
                        AND r.import_id=scheduled_first_publication_events.import_id
                        AND r.import_version_id=scheduled_first_publication_events.import_version_id
                        AND r.content_version_id=scheduled_first_publication_events.content_version_id
                        AND r.body_sha256=scheduled_first_publication_events.body_sha256
                        AND r.id>scheduled_first_publication_events.id) ORDER BY id DESC LIMIT 1""",
                    (blog["blog_record_id"], imported["id"], imported["import_version_id"],
                     imported["content_version_id"], hashlib.sha256(str(imported["body_markdown"]).encode()).hexdigest()),
                ).fetchone()
                if not first:
                    continue
            else:
                first = None
            duplicate_job = conn.execute(
                "SELECT id FROM publishing_jobs WHERE blog_id=%s AND content_version_id=%s",
                (blog["blog_record_id"], imported["content_version_id"]),
            ).fetchone()
            if duplicate_job:
                continue
            eligibility_blog = {**blog, "id": blog["blog_record_id"]}
            reasons = _scheduled_eligibility(conn, imported, {
                "id": imported["import_version_id"], "content_version_id": imported["content_version_id"],
            }, eligibility_blog)
            if reasons:
                held += 1
                continue
            recent_check = conn.execute(
                """SELECT payload,created_at FROM audit_events
                WHERE event_type='publication.scheduled_auto.remote_duplicate_check'
                  AND payload->>'content_version_id'=%s AND payload->>'blog_record_id'=%s
                ORDER BY id DESC LIMIT 1""",
                (str(imported["content_version_id"]), str(blog["blog_record_id"])),
            ).fetchone()
            if (recent_check and recent_check["payload"].get("result") == "found"):
                held += 1
                continue
            if not (recent_check and recent_check["payload"].get("result") == "clear"
                    and recent_check["created_at"] >= datetime.now(UTC) - timedelta(minutes=30)):
                remote_check = find_remote_duplicate(UUID(str(blog["blog_record_id"])), str(imported["title"]))
                conn.execute(
                    "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES (%s,%s,%s,%s)",
                    ("publication.scheduled_auto.remote_duplicate_check", blog["blog_record_id"],
                     blog["blog_language"], Jsonb({"import_id": str(imported["id"]),
                      "content_version_id": str(imported["content_version_id"]),
                      "blog_record_id": str(blog["blog_record_id"]), "result": remote_check["status"],
                      "reason": remote_check["reason"], "scanned_posts": remote_check.get("scanned_posts"),
                      "post_id": remote_check.get("post_id"), "read_only": True})),
                )
                if remote_check["status"] != "clear":
                    held += 1
                    continue
            daily = conn.execute(
                """SELECT count(*)::int AS n FROM publishing_jobs WHERE publication_lane='scheduled_auto'
                AND blog_id=%s AND status IN ('queued','running','uncertain','succeeded')
                AND scheduled_at >= date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'""",
                (blog["blog_record_id"],),
            ).fetchone()["n"]
            if int(daily) >= int(policy["daily_limit"]):
                held += 1
                continue
            policy_row = conn.execute(
                "SELECT id FROM publishing_policies WHERE blog_id=%s ORDER BY active DESC,id LIMIT 1",
                (blog["blog_record_id"],),
            ).fetchone()
            if not policy_row:
                held += 1
                continue
            job_key = hashlib.sha256(
                f"scheduled-auto:{blog['blog_record_id']}:{imported['content_version_id']}:{imported['import_hash']}".encode()
            ).hexdigest()
            job = conn.execute(
                """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
                scheduled_at,status,publication_state,adapter_type,simulation_only,oauth_connection_id,
                live_stage,publication_lane)
                VALUES (%s,%s,%s,%s,now(),'queued','publication_queued','blogger_live',false,%s,
                  'draft_needed','scheduled_auto') ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                (policy_row["id"], blog["blog_record_id"], imported["content_version_id"], job_key,
                 blog["oauth_connection_id"]),
            ).fetchone()
            if job:
                created += 1
                _append_audit(conn, "publication.scheduled_auto_job.queued", {
                    "job_id": str(job["id"]), "import_id": str(imported["id"]),
                    "import_version_id": str(imported["import_version_id"]),
                    "content_version_id": str(imported["content_version_id"]),
                    "blog_id": str(blog["blog_id"]), "first_post_approval_event_id": first["id"] if first else None,
                    "publication_lane": "scheduled_auto", "simulation_only": False,
                })
        return {"created": created, "held": held, "policy_active": True,
                "first_post_confirmed": bool(prior_success)}


def process_next_live_job(*, scheduled_auto_only: bool = False) -> dict[str, Any] | None:
    """Process one fully approved Blogger job; all absent approvals fail closed."""
    enqueue_scheduled_auto_jobs()
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
            retry_count,max_retries,publication_state,live_stage,remote_post_id,oauth_connection_id,
            publication_lane
            FROM publishing_jobs j WHERE NOT j.simulation_only AND j.adapter_type='blogger_live'
              AND (%s=false OR j.publication_lane='scheduled_auto')
              AND j.status='queued' AND j.scheduled_at<=now() AND j.available_at<=now()
            ORDER BY CASE WHEN (SELECT language_code FROM blogger_blogs bb WHERE bb.id=j.blog_id)='en'
            THEN 0 ELSE 1 END,j.scheduled_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (scheduled_auto_only,),
        ).fetchone()
        if job is None:
            return None
        job_id = UUID(str(job["id"]))
        blog_id = UUID(str(job["blog_id"]))
        version_id = UUID(str(job["content_version_id"]))
        candidate = publications._candidate(conn, version_id, blog_id)
        lane = str(job["publication_lane"])
        if lane == "scheduled_auto":
            link = conn.execute(
                """SELECT i.*,v.id AS import_version_id,v.version_number,link.content_version_id,
                blog.id AS blog_record_id,blog.blog_id,blog.language_code AS blog_language,blog.url,
                blog.oauth_connection_id,blog.active,blog.connection_verified_at,g.status AS oauth_status
                FROM external_content_imports i
                JOIN external_content_import_content_links link ON link.import_id=i.id
                JOIN external_content_import_versions v ON v.import_id=i.id AND v.id=link.import_version_id
                JOIN blogger_blogs blog ON blog.id=%s JOIN google_connections g ON g.id=blog.oauth_connection_id
                WHERE link.content_version_id=%s AND i.generation_method='chatgpt_scheduled_export'
                ORDER BY v.version_number DESC LIMIT 1""",
                (blog_id, version_id),
            ).fetchone()
            eligibility_blog = {**dict(link), "id": link["blog_record_id"]} if link else {}
            reasons = _scheduled_eligibility(conn, link, link, eligibility_blog) if link else ["scheduled_import_not_found"]
            policy = conn.execute(
                "SELECT action,approved_blog_ids FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if (not policy or policy["action"] != "enabled"
                    or str(blog_id) not in {str(value) for value in policy["approved_blog_ids"]}):
                reasons.append("scheduled_auto_policy_not_active_for_blog")
            prior_success = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM publishing_jobs WHERE publication_lane='scheduled_auto' AND status='succeeded') AS value"
            ).fetchone()["value"]
            if not prior_success and link:
                digest = hashlib.sha256(str(link["body_markdown"]).encode("utf-8")).hexdigest()
                approved = conn.execute(
                    """SELECT 1 FROM scheduled_first_publication_events e WHERE e.action='approved'
                    AND e.blog_id=%s AND e.import_id=%s AND e.import_version_id=%s
                    AND e.content_version_id=%s AND e.body_sha256=%s AND NOT EXISTS (
                      SELECT 1 FROM scheduled_first_publication_events r WHERE r.action='revoked'
                      AND r.blog_id=e.blog_id AND r.import_id=e.import_id
                      AND r.import_version_id=e.import_version_id AND r.content_version_id=e.content_version_id
                      AND r.body_sha256=e.body_sha256 AND r.id>e.id) LIMIT 1""",
                    (blog_id, link["id"], link["import_version_id"], version_id, digest),
                ).fetchone()
                if not approved:
                    reasons.append("exact_first_publication_approval_missing")
            if candidate is not None and link:
                assessment = conn.execute(
                    """SELECT safe_html,html_sha256 FROM external_content_import_assessments
                    WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1""",
                    (link["id"], link["import_version_id"]),
                ).fetchone()
                if assessment:
                    candidate = dict(candidate)
                    candidate.update({"title": link["title"], "editorial_title": link["title"],
                                      "html_body": assessment["safe_html"],
                                      "blogger_labels": link["blogger_labels"]})
        else:
            reasons = list(publications._assess(dict(candidate) if candidate else None)["reasons"])
        current = conn.execute(
            "SELECT oauth_connection_id,blog_id FROM blogger_blogs WHERE id=%s AND active",
            (blog_id,),
        ).fetchone()
        if not current or str(current["oauth_connection_id"]) != str(job["oauth_connection_id"]):
            reasons.append("blog_oauth_mapping_changed")
        if lane == "scheduled_auto":
            with external_policy.scheduled_publication_context(str(blog_id)):
                publish_operation_approved = external_policy._blogger_operation_is_approved(
                    "blogger_public_publish"
                )
        else:
            publish_operation_approved = external_policy._blogger_operation_is_approved(
                "blogger_public_publish"
            )
        if not publish_operation_approved:
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
    if lane == "scheduled_auto":
        remote_check = find_remote_duplicate(
            blog_id, str(candidate.get("editorial_title") or candidate["title"]),
        )
        if remote_check["status"] != "clear":
            category = "remote_duplicate_found" if remote_check["status"] == "found" else "remote_duplicate_check_unknown"
            with connection() as conn:
                conn.execute(
                    """UPDATE publishing_jobs SET status='blocked',publication_state='publication_blocked',
                    last_error_category=%s,lease_until=NULL,updated_at=now() WHERE id=%s AND status='running'""",
                    (category, job_id),
                )
                _append_audit(conn, "publication.scheduled_auto.remote_duplicate_blocked", {
                    "job_id": str(job_id), "content_version_id": str(version_id),
                    "status": remote_check["status"], "reason": remote_check["reason"],
                    "post_id": remote_check.get("post_id"), "blogger_write_performed": False,
                })
            return {"job_id": str(job_id), "status": "blocked", "reason": category,
                    "remote_duplicate_check": remote_check["status"], "live_write_performed": False}
    if stage == "draft_needed":
        operation = "create_draft"
        write_key = "pubjob-" + str(job_id) + "-draft"
        try:
            result = publisher.create_draft(
                write_key, blog_id,
                str(candidate.get("editorial_title") or candidate["title"]),
                str(candidate["html_body"]),
                list(candidate.get("blogger_labels") or []),
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
        if lane == "scheduled_auto":
            with external_policy.scheduled_publication_context(str(blog_id)):
                result = publisher.publish_draft(
                    write_key, blog_id, str(claimed["remote_post_id"]),
                    source_draft_key=source_draft_key,
                )
        else:
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
    backoff_seconds: int = 30, *, allow_private_drafts: bool = False,
    allow_live_publications: bool = False, allow_scheduled_auto_publications: bool = False,
) -> dict[str, Any] | None:
    """Process one explicitly approved private draft or one due fake job."""
    if not 0 <= backoff_seconds <= 3600:
        raise ValueError("invalid_backoff")
    if allow_scheduled_auto_publications:
        live = process_next_live_job(scheduled_auto_only=True)
        if live is not None:
            return {"job_type": "scheduled_auto_blogger_live", **live,
                    "simulation_only": False, "auto_enabled": True}
    if allow_live_publications:
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
    backoff_seconds: int = 30, *, allow_private_drafts: bool = False,
    allow_live_publications: bool = False, allow_scheduled_auto_publications: bool = False,
) -> dict[str, Any]:
    heartbeat("running", service_name="publication_worker")
    try:
        result = tick(backoff_seconds, allow_private_drafts=allow_private_drafts,
                      allow_live_publications=allow_live_publications,
                      allow_scheduled_auto_publications=allow_scheduled_auto_publications)
        return {
            "processed": result is not None,
            "result": result,
            "private_draft_creation_enabled": allow_private_drafts,
            "public_publication_enabled": False,
            "live_publication_dispatch_enabled": allow_live_publications,
            "scheduled_auto_publication_dispatch_enabled": allow_scheduled_auto_publications,
        }
    except Exception:
        heartbeat("degraded", "publication_worker_failed", "publication_worker")
        raise
    finally:
        heartbeat("stopped", service_name="publication_worker")


def run_forever(
    poll_seconds: int = 15,
    backoff_seconds: int = 30,
    *,
    allow_private_drafts: bool = False,
    allow_live_publications: bool = False,
    allow_scheduled_auto_publications: bool = False,
    cycle_limit: int | None = None,
) -> None:
    """Run queue polling under a PostgreSQL singleton lock and live heartbeat.

    External writes remain controlled by the explicit flags and the existing
    Publisher policy gates. The default invocation is a mock-only worker.
    `cycle_limit` exists only to make lifecycle behavior deterministic in tests.
    """
    if not 1 <= poll_seconds <= 3600 or not 0 <= backoff_seconds <= 3600:
        raise ValueError("invalid_worker_poll_policy")
    if cycle_limit is not None and cycle_limit < 1:
        raise ValueError("invalid_cycle_limit")
    guard = acquire_process_lock("publication_worker")
    stop = threading.Event()
    degraded = threading.Event()
    old_handlers: dict[int, Any] = {}

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            old_handlers[signum] = signal.signal(signum, request_stop)
        except ValueError:
            # Non-main-thread invocation is used only by a few test harnesses;
            # the database stop marker remains available there.
            pass

    def beat() -> None:
        while not stop.is_set():
            try:
                heartbeat(
                    "degraded" if degraded.is_set() else "running",
                    "publication_worker_cycle_failed" if degraded.is_set() else None,
                    "publication_worker",
                )
            except psycopg.Error:
                degraded.set()
            stop.wait(15)

    heartbeat_thread = threading.Thread(
        target=beat, name="publication-worker-heartbeat", daemon=True
    )
    cycles = 0
    failures = 0
    heartbeat_thread.start()
    try:
        while not stop.is_set():
            if consume_worker_stop_request(service_name="publication_worker"):
                print("Graceful stop requested between publication cycles.", flush=True)
                break
            try:
                result = tick(
                    backoff_seconds,
                    allow_private_drafts=allow_private_drafts,
                    allow_live_publications=allow_live_publications,
                    allow_scheduled_auto_publications=allow_scheduled_auto_publications,
                )
                failures = 0
                degraded.clear()
                if result is not None:
                    print(json.dumps(result, ensure_ascii=True, default=str), flush=True)
            except Exception as exc:  # noqa: BLE001 - keep service alive with bounded backoff and sanitized diagnostics
                failures += 1
                degraded.set()
                print(
                    json.dumps({
                        "status": "degraded",
                        "error_category": "publication_worker_cycle_failed",
                        "error_type": type(exc).__name__,
                        "retry_number": failures,
                    }),
                    flush=True,
                )
            cycles += 1
            if cycle_limit is not None and cycles >= cycle_limit:
                break
            delay = (
                min(300, max(poll_seconds, backoff_seconds) * (2 ** min(failures - 1, 4)))
                if failures else poll_seconds
            )
            stop.wait(delay)
    finally:
        stop.set()
        heartbeat_thread.join(timeout=3)
        try:
            heartbeat("stopped", service_name="publication_worker")
        finally:
            release_process_lock(guard, "publication_worker")
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
