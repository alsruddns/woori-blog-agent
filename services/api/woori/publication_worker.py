"""Lease-based Blogger publication worker with an explicit continuous service loop."""

from __future__ import annotations

import hashlib
import json
import re
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
from .scheduled_auto_verification import (
    evaluate_scheduled_evidence,
    sanitize_scheduled_body,
    verified_scheduled_claim_ids,
)
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


def _scheduled_eligibility(conn: Any, imported: Any, version: Any, blog: Any) -> dict[str, Any]:
    """Apply the publish-first policy only to scoped Codex scheduled exports."""
    reasons: list[str] = []
    if imported["generation_method"] != "chatgpt_scheduled_export":
        reasons.append("not_a_scheduled_export")
    assessment = conn.execute(
        """SELECT machine_passed,safe_html,html_sha256,seo_checks,generation_ready,publish_ready
        FROM external_content_import_assessments
        WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1""",
        (imported["id"], version["id"]),
    ).fetchone()
    machine_reasons, machine_followups = scheduled_publish_first_assessment(assessment)
    reasons.extend(machine_reasons)
    sources = imported["sources"] or []
    verified = conn.execute(
        """SELECT DISTINCT ON (payload->>'source_id') payload FROM audit_events
        WHERE event_type='research.source.live_document_verified' AND payload->>'import_id'=%s
        ORDER BY payload->>'source_id',id DESC""", (str(imported["id"]),)
    ).fetchall()
    verified_by_id = {str(row["payload"].get("source_id")): row["payload"] for row in verified}
    review = conn.execute(
        """SELECT claims_checked,rights_reviewed FROM external_content_import_review_events
        WHERE import_id=%s AND version_id=%s AND event_type='editorial_review_passed'
        ORDER BY created_at DESC,id DESC LIMIT 1""",
        (imported["id"], version["id"]),
    ).fetchone()
    proof_by_id: dict[str, dict[str, Any]] = {}
    for source_id, proof in verified_by_id.items():
        proof_by_id[source_id] = {
            **proof,
            "source_url": proof.get("source_url") or proof.get("url"),
            "source_body_sha256": proof.get("source_body_sha256") or proof.get("body_sha256"),
        }
    article_body = conn.execute(
        "SELECT body FROM content_versions WHERE id=%s", (version.get("content_version_id"),)
    ).fetchone()
    body = str(article_body["body"]) if article_body else ""
    verified_claim_ids = verified_scheduled_claim_ids(imported, proof_by_id)
    sanitizer = sanitize_scheduled_body(
        body, imported.get("claims") or [], verified_claim_ids=verified_claim_ids,
    )
    manifest = conn.execute(
        """SELECT payload FROM audit_events
        WHERE event_type='publication.scheduled_auto.sanitization_revision_created'
          AND payload->>'output_version_id'=%s AND payload->>'output_sha256'=%s
        ORDER BY id DESC LIMIT 1""", (str(version["id"]), hashlib.sha256(body.encode("utf-8")).hexdigest()),
    ).fetchone()
    if sanitizer["changed"]:
        reasons.append("scheduled_sanitized_revision_required"
                       if sanitizer["substantive_blocks_remaining"] >= 2
                       else "no_supported_body_after_sanitization")
    cited_source_ids = set(re.findall(r"\[source:([A-Za-z0-9_-]+)\]", body))
    claims = imported.get("claims") or []
    if manifest:
        retained_claim_ids = {str(value) for value in manifest["payload"].get("retained_claim_ids", [])}
        claims = [claim for claim in claims if str(claim.get("claim_id")) in retained_claim_ids]
    else:
        claims = [claim for claim in claims if {str(value) for value in claim.get("source_ids") or []}.issubset(cited_source_ids)]
    used_sources = [source for source in sources if str(source.get("source_id")) in cited_source_ids]
    filtered_import = {**dict(imported), "claims": claims, "sources": used_sources}
    evidence_result = evaluate_scheduled_evidence(
        filtered_import,
        version_sha256=str(imported.get("import_hash") or ""),
        source_proofs=proof_by_id,
        human_review=review,
        scheduled_publish_first=True,
        article_body=body,
    )
    evidence_result["followups"].extend(machine_followups)
    reasons.extend(evidence_result["reasons"])
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
    unique_reasons = list(dict.fromkeys(reasons))
    return {"reasons": unique_reasons, "evidence": evidence_result,
            "sanitizer": sanitizer, "body": body, "assessment": assessment}


def scheduled_publish_first_assessment(assessment: Any) -> tuple[list[str], list[dict[str, str]]]:
    """For scheduled originals, route non-critical evaluation flags to follow-up.

    A usable sanitized HTML document is still mandatory. This never changes the
    stored machine_passed/generation_ready/publish_ready values.
    """
    if not assessment or not assessment.get("safe_html"):
        return ["scheduled_publishable_html_missing"], []
    followups: list[dict[str, str]] = []
    flags = (
        ("machine_passed", "기계 품질 검사 미통과", "medium"),
        ("generation_ready", "원고 생성 준비 평가 미통과", "medium"),
        ("publish_ready", "일반 publish_ready 평가 미통과", "medium"),
    )
    for field, description, severity in flags:
        if assessment.get(field) is not True:
            followups.append({"issue_type": "other", "severity": severity, "description": description})
    return [], followups


def enqueue_scheduled_auto_jobs() -> dict[str, Any]:
    """Enqueue only evidence-reviewed scheduled exports inside the active policy scope."""
    created = 0
    held = 0
    with connection() as conn:
        policy_check = conn.execute(
            "SELECT action FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        global_check = conn.execute(
            "SELECT emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
        ).fetchone()
        candidates = conn.execute(
            """SELECT id FROM external_content_imports WHERE generation_method='chatgpt_scheduled_export'
            ORDER BY received_at,id"""
        ).fetchall()
    if (policy_check and policy_check.get("action") == "enabled"
        and global_check and not global_check.get("emergency_stopped", True)):
        from .content_imports import prepare_scheduled_publishable_version
        for candidate in candidates:
            prepare_scheduled_publishable_version(UUID(str(candidate["id"])))
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
            duplicate_job = conn.execute(
                "SELECT id FROM publishing_jobs WHERE blog_id=%s AND content_version_id=%s",
                (blog["blog_record_id"], imported["content_version_id"]),
            ).fetchone()
            if duplicate_job:
                continue
            eligibility_blog = {**blog, "id": blog["blog_record_id"]}
            eligibility = _scheduled_eligibility(conn, imported, {
                "id": imported["import_version_id"], "content_version_id": imported["content_version_id"],
            }, eligibility_blog)
            reasons = eligibility["reasons"]
            verification_payload = {
                "import_id": str(imported["id"]),
                "import_version_id": str(imported["import_version_id"]),
                "content_version_id": str(imported["content_version_id"]),
                "version_sha256": str(imported["import_hash"]),
                "status": "passed" if not reasons else "held",
                "reasons": reasons,
                "checks": eligibility["evidence"]["checks"],
                "source_ids": eligibility["evidence"]["source_ids"],
                "claim_ids": eligibility["evidence"]["claim_ids"],
                "source_evidence_sha256": eligibility["evidence"]["source_evidence_sha256"],
                "claim_count": eligibility["evidence"]["claim_count"],
                "policy_version": "scheduled-evidence-2-no-first-post-gate",
                "first_publication_approval_required": False,
                "live_write_performed": False,
            }
            prior_assessment = conn.execute(
                """SELECT 1 FROM audit_events WHERE event_type='publication.scheduled_auto.evidence_assessed'
                AND payload->>'import_version_id'=%s AND payload->>'version_sha256'=%s
                AND payload->>'status'=%s AND payload->'reasons'=%s
                AND payload->'checks'=%s AND payload->'source_ids'=%s AND payload->'claim_ids'=%s
                AND payload->'source_evidence_sha256'=%s
                AND payload->>'policy_version'='scheduled-evidence-1' LIMIT 1""",
                (str(imported["import_version_id"]), str(imported["import_hash"]),
                 verification_payload["status"], Jsonb(reasons),
                 Jsonb(eligibility["evidence"]["checks"]),
                 Jsonb(eligibility["evidence"]["source_ids"]),
                 Jsonb(eligibility["evidence"]["claim_ids"]),
                 Jsonb(eligibility["evidence"]["source_evidence_sha256"])),
            ).fetchone()
            if not prior_assessment:
                _append_audit(conn, "publication.scheduled_auto.evidence_assessed", verification_payload)
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
                    "blog_id": str(blog["blog_id"]),
                    "first_publication_approval_required": False,
                    "publication_lane": "scheduled_auto", "simulation_only": False,
                })
                review = conn.execute(
                    """INSERT INTO post_publication_reviews(publishing_job_id,blog_id,content_version_id,
                    import_id,content_id,review_notes) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(publishing_job_id) WHERE publishing_job_id IS NOT NULL DO NOTHING
                    RETURNING id""",
                    (job["id"], blog["blog_record_id"], imported["content_version_id"], imported["id"],
                     imported.get("external_content_id"), "자동 게시 전 생성된 후속 확인 항목입니다."),
                ).fetchone()
                if review:
                    _append_audit(conn, "publication.post_review.prepublication_created", {
                        "review_id": str(review["id"]), "job_id": str(job["id"]),
                        "import_id": str(imported["id"]), "content_version_id": str(imported["content_version_id"]),
                        "post_id": None, "publication_lane": "scheduled_auto",
                    })
                    followups = list(eligibility["evidence"].get("followups", []))
                    seo_followups = {
                        "title_matches_article": ("other", "게시 제목과 검색 제목의 일치 여부를 확인하세요."),
                        "primary_term": ("other", "핵심 검색어와 본문 검색 의도의 자연스러운 일치를 검토하세요."),
                        "search_intent": ("other", "검색 의도 적합성이 자동 측정되지 않았습니다."),
                        "source_links": ("source", "게시된 본문에 출처 링크가 읽기 쉽게 연결됐는지 확인하세요."),
                        "blogger_search_description": ("other", "Blogger 편집 화면에서 검색 설명 표시를 확인하세요."),
                        "blogger_theme_seo": ("other", "Blogger 테마의 검색 표시 설정을 확인하세요."),
                    }
                    current_assessment = eligibility.get("assessment") or {}
                    for check in current_assessment.get("seo_checks", []):
                        if isinstance(check, dict) and check.get("key") in seo_followups and check.get("status") in {"review", "not_measured"}:
                            issue_type, description = seo_followups[check["key"]]
                            followups.append({"issue_type": issue_type, "severity": "low", "description": description})
                    for index, item in enumerate(followups):
                        issue_key = "prepub-review-" + hashlib.sha256(
                            f"{job['id']}:{item['issue_type']}:{item['description']}:{index}".encode()
                        ).hexdigest()[:40]
                        item_row = conn.execute(
                            """INSERT INTO post_publication_review_items(review_id,issue_type,severity,description,idempotency_key)
                            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                            (review["id"], item["issue_type"], item["severity"], item["description"], issue_key),
                        ).fetchone()
                        if item_row:
                            _append_audit(conn, "publication.post_review_item.prepublication_created", {
                                "review_id": str(review["id"]), "item_id": str(item_row["id"]),
                                "job_id": str(job["id"]), "issue_type": item["issue_type"],
                                "severity": item["severity"], "description": item["description"][:500],
                            })
        return {"created": created, "held": held, "policy_active": True,
                "first_publication_approval_required": False}


def process_next_live_job(
    *, scheduled_auto_only: bool = False, manual_confirmed_only: bool = False,
) -> dict[str, Any] | None:
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
              AND (%s=false OR (j.publication_lane='manual' AND EXISTS (
                SELECT 1 FROM manual_publication_approval_events a WHERE a.job_id=j.id
              )))
              AND j.status='queued' AND j.scheduled_at<=now() AND j.available_at<=now()
            ORDER BY CASE WHEN (SELECT language_code FROM blogger_blogs bb WHERE bb.id=j.blog_id)='en'
            THEN 0 ELSE 1 END,j.scheduled_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (scheduled_auto_only, manual_confirmed_only),
        ).fetchone()
        if job is None:
            return None
        job_id = UUID(str(job["id"]))
        blog_id = UUID(str(job["blog_id"]))
        version_id = UUID(str(job["content_version_id"]))
        candidate = publications._candidate(conn, version_id, blog_id)
        lane = str(job["publication_lane"])
        assessment = None
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
            eligibility = _scheduled_eligibility(conn, link, link, eligibility_blog) if link else None
            reasons = eligibility["reasons"] if eligibility else ["scheduled_import_not_found"]
            policy = conn.execute(
                "SELECT action,approved_blog_ids FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if (not policy or policy["action"] != "enabled"
                    or str(blog_id) not in {str(value) for value in policy["approved_blog_ids"]}):
                reasons.append("scheduled_auto_policy_not_active_for_blog")
            if candidate is not None and link:
                assessment = conn.execute(
                    """SELECT safe_html,html_sha256,seo_checks FROM external_content_import_assessments
                    WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1""",
                    (link["id"], link["import_version_id"]),
                ).fetchone()
                if assessment:
                    candidate = dict(candidate)
                    candidate.update({"title": link["title"], "editorial_title": link["title"],
                                      "html_body": assessment["safe_html"],
                                      "blogger_labels": link["blogger_labels"]})
        elif lane == "manual":
            manual_approval = conn.execute(
                """SELECT * FROM manual_publication_approval_events
                WHERE job_id=%s AND blog_id=%s AND content_version_id=%s""",
                (job_id, blog_id, version_id),
            ).fetchone()
            candidate = dict(candidate) if candidate else None
            snapshot = publications._manual_publication_snapshot(conn, candidate)
            reasons = publications._manual_publication_blockers(
                conn, candidate, snapshot, blog_id, ignore_job_id=job_id,
            )
            if not manual_approval:
                reasons.append("exact_manual_publication_confirmation_missing")
            elif any((
                manual_approval["title_sha256"] != snapshot.get("title_sha256"),
                manual_approval["body_sha256"] != snapshot.get("body_sha256"),
                manual_approval["html_sha256"] != snapshot.get("html_sha256"),
                not manual_approval["reviewed_exact_content"],
                not manual_approval["assertions_safe_to_publish"],
                not manual_approval["rights_privacy_harm_checked"],
            )):
                reasons.append("manual_publication_confirmation_payload_mismatch")
            if candidate:
                candidate.update({
                    "editorial_title": snapshot.get("title"),
                    "html_body": snapshot.get("safe_html"),
                    "blogger_labels": snapshot.get("blogger_labels", []),
                })
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
        elif lane == "manual":
            publish_operation_approved = bool(
                manual_approval
                and manual_approval["job_id"] == job_id
                and manual_approval["blog_id"] == blog_id
                and manual_approval["content_version_id"] == version_id
                and manual_approval["title_sha256"] == snapshot.get("title_sha256")
                and manual_approval["body_sha256"] == snapshot.get("body_sha256")
                and manual_approval["html_sha256"] == snapshot.get("html_sha256")
                and external_policy._blogger_policy_approval() is not None
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
    if lane in {"scheduled_auto", "manual"}:
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
                _append_audit(conn, "publication." + lane + ".remote_duplicate_blocked", {
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
        elif lane == "manual":
            assert manual_approval is not None
            with external_policy.manual_publication_context(
                str(job_id), str(blog_id), str(version_id),
                str(manual_approval["title_sha256"]),
                str(manual_approval["body_sha256"]),
                str(manual_approval["html_sha256"]),
            ):
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
                VALUES (%s,%s,%s,%s,%s,%s,'LIVE',now()) ON CONFLICT(blog_id,content_version_id) DO NOTHING
                RETURNING id""",
                (job_id, blog_id, version_id, result["post_id"], result["published_at"], result["url"]),
            )
            record = conn.execute(
                "SELECT id,remote_post_id,remote_url FROM publishing_records WHERE blog_id=%s AND content_version_id=%s",
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
            if lane in {"scheduled_auto", "manual"}:
                review = conn.execute(
                    """UPDATE post_publication_reviews SET publishing_record_id=%s,post_id=%s,updated_at=now()
                    WHERE publishing_job_id=%s AND publishing_record_id IS NULL RETURNING id""",
                    (record["id"], result["post_id"], job_id),
                ).fetchone()
                linked_existing = bool(review)
                review_import_id = str(link["id"]) if lane == "scheduled_auto" and link else (
                    snapshot.get("import_id") if lane == "manual" and snapshot else None
                )
                review_content_id = (
                    str(link.get("external_content_id")) if lane == "scheduled_auto" and link
                    and link.get("external_content_id") else
                    snapshot.get("external_content_id") if lane == "manual" and snapshot else None
                )
                if not review:
                    review = conn.execute(
                    """INSERT INTO post_publication_reviews(publishing_record_id,blog_id,content_version_id,
                    post_id,import_id,content_id) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(publishing_record_id) DO NOTHING
                    RETURNING id""",
                    (record["id"], blog_id, version_id, result["post_id"],
                     review_import_id, review_content_id),
                    ).fetchone()
                review = review or conn.execute(
                    "SELECT id FROM post_publication_reviews WHERE publishing_record_id=%s",
                    (record["id"],),
                ).fetchone()
                review_id = review["id"] if review else None
                if review and (linked_existing or not conn.execute(
                    "SELECT 1 FROM audit_events WHERE event_type='publication.post_review.created' AND payload->>'review_id'=%s LIMIT 1",
                    (str(review_id),),
                ).fetchone()):
                    _append_audit(conn, "publication.post_review.published_linked" if linked_existing else "publication.post_review.created", {
                        "review_id": str(review["id"]), "publishing_record_id": str(record["id"]),
                        "job_id": str(job_id), "import_id": review_import_id if lane == "manual" else (str(link["id"]) if link else None),
                        "content_version_id": str(version_id), "post_id": str(result["post_id"]),
                        "remote_readback_verified": True,
                    })
                soft_followups = {
                    "title_matches_article": ("other", "게시 제목과 검색 제목의 일치 여부를 확인하세요."),
                    "primary_term": ("other", "핵심 검색어와 본문 검색 의도의 자연스러운 일치를 검토하세요."),
                    "search_intent": ("other", "검색 의도 적합성이 자동 측정되지 않았습니다."),
                    "source_links": ("source", "게시된 본문에 출처 링크가 읽기 쉽게 연결됐는지 확인하세요."),
                    "blogger_search_description": ("other", "Blogger 편집 화면에서 검색 설명 표시를 확인하세요."),
                    "blogger_theme_seo": ("other", "Blogger 테마의 검색 표시 설정을 확인하세요."),
                }
                for check in (assessment.get("seo_checks", []) if assessment else []) if review_id else []:
                    if not isinstance(check, dict) or check.get("key") not in soft_followups:
                        continue
                    if check.get("status") not in {"review", "not_measured"}:
                        continue
                    issue_type, description = soft_followups[check["key"]]
                    issue_key = "postreview-" + hashlib.sha256(
                        f"{record['id']}:{check['key']}".encode()
                    ).hexdigest()[:40]
                    if conn.execute(
                        "SELECT 1 FROM post_publication_review_items WHERE review_id=%s AND issue_type=%s AND description=%s LIMIT 1",
                        (review_id, issue_type, description),
                    ).fetchone():
                        continue
                    issue = conn.execute(
                        """INSERT INTO post_publication_review_items(review_id,issue_type,severity,
                        description,idempotency_key) VALUES (%s,%s,'low',%s,%s)
                        ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                        (review_id, issue_type, description, issue_key),
                    ).fetchone()
                    if issue:
                        _append_audit(conn, "publication.post_review_item.created", {
                            "review_id": str(review_id),
                            "item_id": str(issue["id"]), "issue_type": issue_type,
                            "severity": "low", "assessment_key": check["key"],
                            "post_id": str(result["post_id"]),
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
    allow_manual_confirmed_publications: bool = False,
) -> dict[str, Any] | None:
    """Process one explicitly approved private draft or one due fake job."""
    if not 0 <= backoff_seconds <= 3600:
        raise ValueError("invalid_backoff")
    if allow_scheduled_auto_publications:
        live = process_next_live_job(scheduled_auto_only=True)
        if live is not None:
            return {"job_type": "scheduled_auto_blogger_live", **live,
                    "simulation_only": False, "auto_enabled": True}
    if allow_manual_confirmed_publications:
        live = process_next_live_job(manual_confirmed_only=True)
        if live is not None:
            return {"job_type": "manual_confirmed_blogger_live", **live,
                    "simulation_only": False, "auto_enabled": False}
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
    allow_manual_confirmed_publications: bool = False,
) -> dict[str, Any]:
    heartbeat("running", service_name="publication_worker")
    try:
        result = tick(backoff_seconds, allow_private_drafts=allow_private_drafts,
                      allow_live_publications=allow_live_publications,
                      allow_scheduled_auto_publications=allow_scheduled_auto_publications,
                      allow_manual_confirmed_publications=allow_manual_confirmed_publications)
        return {
            "processed": result is not None,
            "result": result,
            "private_draft_creation_enabled": allow_private_drafts,
            "public_publication_enabled": False,
            "live_publication_dispatch_enabled": allow_live_publications,
            "scheduled_auto_publication_dispatch_enabled": allow_scheduled_auto_publications,
            "manual_confirmed_publication_dispatch_enabled": allow_manual_confirmed_publications,
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
    allow_manual_confirmed_publications: bool = False,
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
                    allow_manual_confirmed_publications=allow_manual_confirmed_publications,
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
