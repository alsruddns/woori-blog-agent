"""Explicitly approved Trends publication with post-publication editorial review."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .db import connection

ALLOWED_GEOGRAPHIES = {"KR", "US", "GB", "CA", "AU", "IN", "JP", "TW", "HK", "SG", "PH", "BR"}


def collection_after_activation(slot: Any, activated_at: datetime) -> bool:
    try:
        value = datetime.fromisoformat(str(slot))
        return value.tzinfo is not None and value >= activated_at
    except (ValueError, TypeError):
        return False


def claims_are_publish_verified(claims: Any) -> bool:
    """Require every imported factual claim to retain an explicit verified state."""
    return bool(isinstance(claims, list) and claims) and all(
        isinstance(claim, dict)
        and bool(claim.get("claim_id"))
        and bool(claim.get("source_ids"))
        and claim.get("verification_status") in {"source_span_verified", "corroborated"}
        and claim.get("factual_state") != "unverified"
        for claim in claims
    )


def search_description_is_publishable(value: Any) -> bool:
    description = value.strip() if isinstance(value, str) else ""
    return 30 <= len(description) <= 150


def assess_trends_article(item: dict[str, Any], body: str) -> dict[str, Any]:
    """Post-editing Trends policy: assess format and basic risk, never promote claims."""
    from .editorial_html import markdown_to_blogger_html, sanitize_editorial_html
    reasons: list[str] = []
    title = str(item.get("title") or "").strip()
    if len(title) < 5 or len(body.strip()) < 300:
        reasons.append("article_title_or_body_insufficient")
    if re.search(r"insufficient[_ ]evidence|근거\s*부족|증거\s*부족|情報不足|证据不足", title, re.IGNORECASE):
        reasons.append("insufficient_evidence_is_not_article")
    if re.match(r"\s*(?:I (?:cannot|could not|am unable to) verify|Unable to verify|No sufficient evidence|검증 가능한 정보가 없습니다|근거를 확보하지 못했습니다)", body, re.IGNORECASE):
        reasons.append("insufficient_evidence_is_not_article")
    if re.search(r"</?[A-Za-z][^>]*>|\x00", body):
        reasons.append("unsafe_article_format")
    risk_text = title + " " + body
    if item.get("category") in {"finance", "health"} or re.search(
        r"\b(death|died|suicide|murder|fraud|allegation|cancer|diagnosis|investment|stock price)\b"
        r"|사망|범죄|성폭행|혐의|투자\s*추천|암\s*치료|死亡|犯罪|疑惑|投资建议|治療", risk_text, re.IGNORECASE
    ):
        reasons.append("high_impact_topic_requires_review")
    for claim in item.get("claims") or []:
        if claim.get("verification_status") in {"conflict", "contradicted", "rejected"}:
            reasons.append("known_conflicting_claim")
        excerpt = str(claim.get("evidence_excerpt") or "")
        if len(excerpt) > 200 and excerpt in body:
            reasons.append("long_source_copy_requires_review")
    if any(source.get("rights_status") in {"prohibited", "denied", "permission_denied"}
           for source in item.get("sources") or []):
        reasons.append("known_rights_restriction")
    safe_html = ""
    try:
        safe_html = markdown_to_blogger_html(body, post_title=title,
            summary=str((item.get("seo_metadata") or {}).get("search_description") or ""))
        safe_html, _ = sanitize_editorial_html(safe_html, post_title=title)
    except ValueError:
        reasons.append("unsafe_article_html")
    return {"reasons": sorted(set(reasons)), "safe_html": safe_html,
            "html_sha256": hashlib.sha256(safe_html.encode()).hexdigest(),
            "policy_version": "trends-post-edit-1", "claims_promoted": False,
            "post_publication_review_required": True}


def policy_state(conn: Any) -> dict[str, Any]:
    blogs = conn.execute(
        """SELECT b.id,b.blog_id,b.display_name,b.language_code,b.url,b.active,
          b.oauth_connection_id,b.connection_verified_at,b.test_publish_verified_at,
          g.status AS oauth_status,g.scopes,
          GREATEST((SELECT max(d.verified_at) FROM blogger_draft_receipts d WHERE d.blog_id=b.id),
            (SELECT max(r.remote_verified_at) FROM publishing_records r JOIN publishing_jobs j ON j.id=r.job_id
              WHERE r.blog_id=b.id AND j.publication_lane='trends_auto' AND r.remote_status='LIVE')) AS last_completed_at,
          COALESCE(array_agg(DISTINCT m.geo) FILTER (WHERE m.enabled),ARRAY[]::text[]) AS mapped_geos
        FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        LEFT JOIN trend_blog_geo_authoring m ON m.blog_id=b.id
        GROUP BY b.id,g.status,g.scopes ORDER BY b.display_name,b.id"""
    ).fetchall()
    latest = conn.execute(
        """SELECT DISTINCT ON(blog_id) id,blog_id,enabled,allowed_geos,daily_limit,publication_mode,
          actor_label,reason,created_at FROM trends_publication_policy_events
        ORDER BY blog_id,id DESC"""
    ).fetchall()
    policies = {str(row["blog_id"]): dict(row) for row in latest}
    from . import external_policy
    public_approved = external_policy._blogger_public_publish_approval() is not None
    emergency = conn.execute("SELECT emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''").fetchone()
    for blog in blogs:
        blockers = []
        if not blog["mapped_geos"]: blockers.append("country_mapping_required")
        if blog["oauth_status"] != "connected" or list(blog["scopes"] or []) != ["https://www.googleapis.com/auth/blogger"]:
            blockers.append("blogger_write_oauth_required")
        if not blog["test_publish_verified_at"]: blockers.append("actual_write_verification_required")
        if not _recent_identity_verification(conn, blog["id"], str(blog["blog_id"])):
            blockers.append("fresh_blog_identity_verification_required")
        blog['public_approval_present'] = public_approved or external_policy._trends_public_write_approval(str(blog['id'])) is not None
        if not blog['public_approval_present']:
            blockers.append("authenticated_public_publish_approval_required")
        blog["draft_activation_blockers"] = [b for b in blockers if b not in {"actual_write_verification_required", "authenticated_public_publish_approval_required"}]
        blog["activation_blockers"] = blockers
        blog["activation_ready"] = not blockers
        blog['authoring'] = conn.execute("""SELECT q.state request_state,j.id job_id,j.state,j.error_code,j.keyword,j.import_id,j.content_version_id,j.updated_at
            FROM trend_generation_requests q LEFT JOIN codex_authoring_jobs j ON j.id=q.authoring_job_id
            WHERE q.contract->>'target_blog_id'=%s ORDER BY q.created_at DESC,q.id DESC LIMIT 1""",(str(blog['id']),)).fetchone()
        blog['delivery'] = conn.execute("""SELECT id,status,publication_state,publication_mode,last_error_category,available_at,remote_post_id
            FROM publishing_jobs WHERE blog_id=%s AND publication_lane='trends_auto' ORDER BY scheduled_at DESC,id DESC LIMIT 1""",(blog['id'],)).fetchone()
    from .keyword_jobs import authoring_backoff
    return {"policies": [{**dict(blog), "policy": policies.get(str(blog["id"]))}
                          for blog in blogs],
            "supported_geographies": sorted(ALLOWED_GEOGRAPHIES),
            "provenance": "codex_trends_export", "publication_lane": "trends_auto",
            "emergency_stopped": not emergency or bool(emergency['emergency_stopped']),
            'codex_backoff':authoring_backoff(conn)}


def record_policy(conn: Any, request: Any) -> dict[str, Any]:
    expected = "ENABLE TRENDS AUTO PUBLICATION" if request.enabled else "STOP TRENDS AUTO PUBLICATION"
    if request.publication_mode == "publish" and request.confirmation != expected:
        raise HTTPException(422, "Explicit Trends publication confirmation is required")
    blog = conn.execute(
        """SELECT b.id,b.blog_id,b.language_code,b.active,b.oauth_connection_id,
          b.connection_verified_at,b.test_publish_verified_at,g.status AS oauth_status,g.scopes
        FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        WHERE b.id=%s""", (request.blog_id,),
    ).fetchone()
    if not blog or not blog["active"]:
        raise HTTPException(404, "Active registered Blogger target not found")
    mapped = {str(row["geo"]) for row in conn.execute(
        "SELECT geo FROM trend_blog_geo_authoring WHERE blog_id=%s AND enabled", (request.blog_id,)
    ).fetchall()}
    geos = sorted(set(request.allowed_geos))
    if not set(geos).issubset(ALLOWED_GEOGRAPHIES) or not set(geos).issubset(mapped):
        raise HTTPException(409, "Trends countries must be explicitly mapped to this Blogger first")
    if request.enabled:
        from .google_http import WRITE_SCOPE
        if (not geos or not blog["blog_id"] or not blog["connection_verified_at"]
                or (request.publication_mode == "publish" and not blog["test_publish_verified_at"]) or blog["oauth_status"] != "connected"
                or list(blog["scopes"] or []) != [WRITE_SCOPE]):
            raise HTTPException(409, "Enabled policy requires a verified Blogger write connection and explicit country mapping")
        if not _recent_identity_verification(conn, request.blog_id, str(blog["blog_id"])):
            raise HTTPException(409, "Run a fresh read-only Blogger identity verification before enabling Trends Auto")
        from . import external_policy
        if external_policy._blogger_policy_approval() is None:
            raise HTTPException(409, "Blogger zero-cost operations approval is unavailable")
    prior = conn.execute(
        "SELECT id,blog_id,enabled,allowed_geos,daily_limit,publication_mode FROM trends_publication_policy_events WHERE idempotency_key=%s",
        (request.idempotency_key,),
    ).fetchone()
    if prior:
        if (str(prior["blog_id"]) != str(request.blog_id) or bool(prior["enabled"]) != request.enabled
                or sorted(prior["allowed_geos"]) != geos
                or prior["daily_limit"] != request.daily_limit or prior["publication_mode"] != request.publication_mode):
            raise HTTPException(409, "Idempotency key conflicts with an earlier Trends policy event")
        return {"event_id": prior["id"], "duplicate": True, "enabled": request.enabled}
    if request.enabled and request.publication_mode == "publish":
        # This authenticated API request contains the explicit enable phrase,
        # actor and reason; never synthesize approval from an agent execution.
        conn.execute("INSERT INTO audit_events(event_type,blog_id,payload) VALUES (%s,%s,%s)",
            ("publication.trends_public_write.approved", request.blog_id, Jsonb({
                "blog_record_id": str(request.blog_id), "blogger_blog_id": str(blog["blog_id"]),
                "actor_label": request.actor_label, "reason": request.reason,
                "confirmation": request.confirmation, "policy_version": 1,
                "scope": "trends_auto", "allowed_geos": geos,
                "content_policy": "trends-post-edit-1", "verified_claim_required": False,
                "post_publication_review_required": True,
            })))
    previous = conn.execute(
        "SELECT id,enabled,allowed_geos,daily_limit,publication_mode FROM trends_publication_policy_events WHERE blog_id=%s ORDER BY id DESC LIMIT 1",
        (request.blog_id,),
    ).fetchone()
    saved = conn.execute(
        """INSERT INTO trends_publication_policy_events(blog_id,enabled,allowed_geos,daily_limit,publication_mode,
          actor_label,reason,idempotency_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,created_at""",
        (request.blog_id, request.enabled, geos, request.daily_limit, request.publication_mode,
         request.actor_label, request.reason, request.idempotency_key),
    ).fetchone()
    payload = {"event_id": saved["id"], "blog_record_id": str(request.blog_id),
        "blogger_blog_id": str(blog["blog_id"]), "enabled": request.enabled,
        "allowed_geos": geos, "daily_limit": request.daily_limit,
        "actor_label": request.actor_label, "reason": request.reason,
        "previous": dict(previous) if previous else None,
        "provenance": "codex_trends_export", "public_write_performed": False}
    payload["publication_mode"] = request.publication_mode
    payload["content_policy"] = "trends-post-edit-1"
    conn.execute("INSERT INTO audit_events(event_type,blog_id,payload) VALUES(%s,%s,%s)",
        ("publication.trends_auto.policy_changed", request.blog_id, Jsonb(payload)))
    return {"event_id": saved["id"], "created_at": saved["created_at"],
            "enabled": request.enabled, "allowed_geos": geos, "daily_limit": request.daily_limit, "publication_mode": request.publication_mode}


def _recent_identity_verification(conn: Any, blog_id: UUID, blogger_id: str) -> bool:
    row = conn.execute(
        """SELECT payload,created_at FROM audit_events
        WHERE event_type IN ('publication.scheduled_auto.connection_check','publication.trends_auto.connection_check')
          AND payload->'results' @> %s::jsonb
        ORDER BY id DESC LIMIT 1""", (Jsonb([{"blog_record_id": str(blog_id)}]),)
    ).fetchone()
    if not row:
        return False
    from datetime import UTC, datetime, timedelta
    if row["created_at"] < datetime.now(UTC) - timedelta(hours=24):
        return False
    return any(str(item.get("blog_record_id")) == str(blog_id) and item.get("verified")
               and str(item.get("remote_blog_id")) == blogger_id
               for item in row["payload"].get("results", []) if isinstance(item, dict))


def validate_trends_job(conn: Any, blog_id: UUID, content_version_id: UUID) -> dict[str, Any]:
    """Recheck Trends lineage, basic article safety, policy, and latest version."""
    row = conn.execute(
        """SELECT i.*,iv.title,iv.body_markdown,iv.id AS import_version_id,iv.version_number,iv.content_sha256 AS import_hash,
          link.content_version_id,j.id AS authoring_job_id,j.job_type,j.state AS authoring_state,
          j.error_code AS authoring_error,q.id AS trend_request_id,q.contract,t.id AS trend_topic_id,
          b.id AS blog_record_id,b.blog_id,b.language_code AS blog_language,b.active,b.connection_verified_at,
          b.oauth_connection_id,g.status AS oauth_status,g.scopes,a.machine_passed,a.safe_html,a.html_sha256,
          locale.language_code AS content_language,locale.target_country,cv.group_id,cv.localization_id
        FROM external_content_imports i
        JOIN external_content_import_content_links link ON link.import_id=i.id
        JOIN external_content_import_versions iv ON iv.id=link.import_version_id AND iv.import_id=i.id
        JOIN content_versions cv ON cv.id=link.content_version_id
        JOIN codex_authoring_jobs j ON j.import_id=i.id AND j.content_version_id=link.content_version_id
        JOIN trend_generation_requests q ON q.authoring_job_id=j.id
        JOIN trend_topics t ON t.id=q.topic_id
        JOIN blogger_blogs b ON b.id=%s JOIN google_connections g ON g.id=b.oauth_connection_id
        JOIN content_localizations locale ON locale.id=cv.localization_id
        LEFT JOIN LATERAL (SELECT machine_passed,safe_html,html_sha256 FROM external_content_import_assessments
          WHERE import_id=i.id AND version_id=iv.id ORDER BY assessed_at DESC,id DESC LIMIT 1) a ON true
        WHERE link.content_version_id=%s AND i.generation_method='codex_trends_export'
          AND j.job_type='google_trends' AND j.state='imported_review'
          AND j.error_code IS NULL AND q.state='imported'
          AND iv.version_number=(SELECT max(v2.version_number) FROM external_content_import_versions v2 WHERE v2.import_id=i.id)
        ORDER BY i.received_at DESC,i.id DESC LIMIT 1""", (blog_id, content_version_id),
    ).fetchone()
    reasons: list[str] = []
    if not row:
        return {"row": None, "assessment": None, "reasons": ["trends_provenance_or_import_link_missing"]}
    row = dict(row)
    policy = conn.execute(
        "SELECT id,enabled,allowed_geos,daily_limit,publication_mode FROM trends_publication_policy_events WHERE blog_id=%s ORDER BY id DESC LIMIT 1",
        (blog_id,),
    ).fetchone()
    geo = str(row["contract"].get("source_country") or "")
    if not policy or not policy["enabled"] or geo not in set(policy["allowed_geos"] or []):
        reasons.append("trends_publication_policy_inactive_or_geo_not_allowed")
    if (str(row["contract"].get("target_blog_id")) != str(blog_id)
            or str(row["contract"].get("target_language")) != str(row["blog_language"])
            or str(row["contract"].get("target_country")) != str(row["target_country"])):
        reasons.append("trends_target_mapping_mismatch")
    if not conn.execute("SELECT 1 FROM trend_blog_geo_authoring WHERE blog_id=%s AND geo=%s AND enabled",
                        (blog_id, geo)).fetchone():
        reasons.append("enabled_trend_blog_geo_mapping_required")
    if not row["active"] or not row["connection_verified_at"] or row["oauth_status"] != "connected":
        reasons.append("blog_or_oauth_not_verified")
    if list(row["scopes"] or []) != ["https://www.googleapis.com/auth/blogger"]:
        reasons.append("blogger_write_oauth_not_verified")
    latest = conn.execute(
        "SELECT id FROM content_versions WHERE group_id=%s AND localization_id=%s ORDER BY version DESC,created_at DESC,id DESC LIMIT 1",
        (row["group_id"], row["localization_id"]),
    ).fetchone()
    if not latest or str(latest["id"]) != str(content_version_id):
        reasons.append("stale_content_version")
    body = conn.execute("SELECT body FROM content_versions WHERE id=%s", (content_version_id,)).fetchone()
    assessment = assess_trends_article(row, str(body["body"] if body else ""))
    reasons.extend(assessment["reasons"])
    row["safe_html"] = assessment["safe_html"]
    row["html_sha256"] = assessment["html_sha256"]
    return {"row": row, "assessment": assessment, "reasons": list(dict.fromkeys(reasons)),
            "policy": dict(policy) if policy else None}


def enqueue_trends_auto_jobs() -> dict[str, int]:
    """Enqueue current, explicitly scoped Trends imports under the post-edit policy."""
    from . import external_policy
    from .scheduled_duplicates import find_remote_duplicate

    created = held = 0
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('trends-publication-enqueue',0))")
        emergency = conn.execute(
            "SELECT emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
        ).fetchone()
        if not emergency or emergency["emergency_stopped"]:
            return {"created": 0, "held": 0}
        policies = conn.execute(
            """SELECT DISTINCT ON(p.blog_id) p.*,b.language_code,b.blog_id AS blogger_id
            FROM trends_publication_policy_events p JOIN blogger_blogs b ON b.id=p.blog_id
            ORDER BY p.blog_id,p.id DESC"""
        ).fetchall()
        for policy in policies:
            if not policy["enabled"]:
                continue
            blog_id = UUID(str(policy["blog_id"]))
            allowed_geos = set(policy["allowed_geos"])
            candidates = conn.execute(
                """SELECT i.*,iv.title,iv.body_markdown,iv.id AS import_version_id,iv.version_number,iv.content_sha256 AS import_hash,
                    link.content_version_id,cv.group_id,cv.localization_id,cv.version AS content_version,
                    j.id AS authoring_job_id,j.job_type,j.state AS authoring_state,j.evidence AS authoring_evidence,
                    j.error_code AS authoring_error,q.id AS trend_request_id,q.contract,
                    t.id AS trend_topic_id,b.id AS blog_record_id,b.blog_id,
                    b.language_code AS blog_language,b.active,b.connection_verified_at,b.test_publish_verified_at,
                    b.oauth_connection_id,g.status AS oauth_status,g.scopes,
                    a.machine_passed,a.safe_html,a.html_sha256,a.seo_checks,
                    locale.language_code AS content_language,locale.target_country
                FROM external_content_imports i
                JOIN external_content_import_content_links link ON link.import_id=i.id
                JOIN external_content_import_versions iv ON iv.id=link.import_version_id AND iv.import_id=i.id
                JOIN content_versions cv ON cv.id=link.content_version_id
                JOIN codex_authoring_jobs j ON j.import_id=i.id
                JOIN trend_generation_requests q ON q.authoring_job_id=j.id AND q.state='imported'
                JOIN trend_topics t ON t.id=q.topic_id
                JOIN blogger_blogs b ON b.id=%s
                JOIN google_connections g ON g.id=b.oauth_connection_id
                JOIN content_localizations locale ON locale.id=cv.localization_id
                LEFT JOIN LATERAL (SELECT machine_passed,safe_html,html_sha256,seo_checks
                  FROM external_content_import_assessments WHERE import_id=i.id AND version_id=iv.id
                  ORDER BY assessed_at DESC,id DESC LIMIT 1) a ON true
                WHERE i.generation_method='codex_trends_export' AND j.job_type='google_trends'
                  AND j.state='imported_review' AND j.error_code IS NULL
                  AND iv.version_number=(SELECT max(i2.version_number) FROM external_content_import_versions i2 WHERE i2.import_id=i.id)
                  AND link.content_version_id=j.content_version_id
                  AND q.contract->>'target_blog_id'=%s
                  AND q.contract->>'target_language'=%s
                ORDER BY i.received_at,i.id""", (blog_id, str(blog_id), policy["language_code"]),
            ).fetchall()
            for item in candidates:
                if not collection_after_activation(item["contract"].get("collection_slot"), policy["created_at"]):
                    held += 1
                    _record_hold(conn, item, blog_id, ["collection_predates_policy_activation"])
                    continue
                geo = str(item["contract"].get("source_country") or "")
                if geo not in allowed_geos:
                    continue
                # Require an explicitly enabled authoring map as well as the
                # separate Trends publication scope. CN is never inferred.
                mapped = conn.execute("SELECT 1 FROM trend_blog_geo_authoring WHERE blog_id=%s AND geo=%s AND enabled",
                    (blog_id, geo)).fetchone()
                if not mapped:
                    held += 1
                    continue
                existing = conn.execute(
                    """SELECT id,status FROM publishing_jobs WHERE blog_id=%s AND content_version_id=%s
                    AND NOT simulation_only AND adapter_type='blogger_live'
                    ORDER BY updated_at DESC,id DESC LIMIT 1""",
                    (blog_id, item["content_version_id"]),
                ).fetchone()
                if existing:
                    continue
                latest = conn.execute(
                    """SELECT id FROM content_versions WHERE group_id=%s AND localization_id=%s
                    ORDER BY version DESC,created_at DESC,id DESC LIMIT 1""",
                    (item["group_id"], item["localization_id"]),
                ).fetchone()
                reasons: list[str] = []
                if not latest or str(latest["id"]) != str(item["content_version_id"]): reasons.append("stale_content_version")
                if not item["active"] or not item["connection_verified_at"] or item["oauth_status"] != "connected": reasons.append("blog_or_oauth_not_verified")
                if list(item["scopes"] or []) != ["https://www.googleapis.com/auth/blogger"]: reasons.append("blogger_write_oauth_not_verified")
                if item["content_language"] != item["blog_language"]: reasons.append("blog_language_mismatch")
                if str(item["target_country"]) != str(item["contract"].get("target_country")): reasons.append("blog_country_mismatch")
                body_row = conn.execute("SELECT body FROM content_versions WHERE id=%s", (item["content_version_id"],)).fetchone()
                safety = assess_trends_article(dict(item), str(body_row["body"] if body_row else ""))
                reasons.extend(safety["reasons"])
                if reasons:
                    held += 1
                    _record_hold(conn, item, blog_id, reasons)
                    continue
                policy_check = external_policy._blogger_policy_approval()
                if not policy_check:
                    held += 1
                    _record_hold(conn, item, blog_id, ["blogger_zero_cost_policy_required"])
                    continue
                with external_policy.trends_publication_context(str(blog_id)):
                    if not external_policy._blogger_operation_is_approved("blogger_public_publish" if policy["publication_mode"] == "publish" else "blogger_draft_create"):
                        held += 1
                        _record_hold(conn, item, blog_id, ["trends_publication_policy_inactive"])
                        continue
                remote = find_remote_duplicate(blog_id, str(item["title"]), include_drafts=True)
                if remote["status"] != "clear":
                    held += 1
                    _record_hold(conn, item, blog_id, ["remote_duplicate_found" if remote["status"] == "found" else "remote_duplicate_check_unknown"])
                    continue
                count = conn.execute(
                    """SELECT (SELECT count(*) FROM publishing_records WHERE blog_id=%s
                         AND published_at>=date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')+
                       (SELECT count(*) FROM publishing_jobs WHERE blog_id=%s AND publication_lane='trends_auto'
                         AND status IN ('queued','running','uncertain','succeeded')
                         AND scheduled_at>=date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul') AS n""",
                    (blog_id, blog_id),
                ).fetchone()
                if not count:
                    held += 1
                    _record_hold(conn, item, blog_id, ["trends_publication_count_unavailable"])
                    continue
                if policy["daily_limit"] is not None and int(count["n"]) >= int(policy["daily_limit"]):
                    held += 1
                    _record_hold(conn, item, blog_id, ["trends_daily_publication_limit"])
                    continue
                policy_row = conn.execute(
                    """SELECT p.id FROM publishing_policies p JOIN language_profiles profile ON profile.id=p.profile_id
                    WHERE p.blog_id=%s AND profile.language_code=%s AND profile.target_country=%s
                    ORDER BY p.active DESC,p.id LIMIT 1""",
                    (blog_id, item["content_language"], item["target_country"]),
                ).fetchone()
                if not policy_row:
                    held += 1
                    _record_hold(conn, item, blog_id, ["publication_policy_missing"])
                    continue
                topic_id = str(item["trend_topic_id"])
                slot = str(item["contract"].get("collection_slot") or "")
                key = hashlib.sha256(f"trends-auto:{blog_id}:{item['content_version_id']}:{topic_id}:{slot}".encode()).hexdigest()
                job = conn.execute(
                    """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
                    scheduled_at,status,publication_state,adapter_type,simulation_only,oauth_connection_id,
                    live_stage,publication_lane,publication_mode,trends_policy_event_id)
                    VALUES(%s,%s,%s,%s,now(),'queued','publication_queued','blogger_live',false,%s,'draft_needed','trends_auto',%s,%s)
                    ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                    (policy_row["id"], blog_id, item["content_version_id"], key, item["oauth_connection_id"], policy["publication_mode"], policy["id"]),
                ).fetchone()
                if not job:
                    continue
                created += 1
                _record_hold(conn, item, blog_id, [], job_id=job["id"])
                _append_audit(conn, "publication.trends_auto_job.queued", {
                    "job_id": str(job["id"]), "import_id": str(item["id"]),
                    "import_version_id": str(item["import_version_id"]),
                    "content_version_id": str(item["content_version_id"]),
                    "trend_topic_id": topic_id, "trend_request_id": str(item["trend_request_id"]),
                    "collection_slot": slot, "source_country": geo, "blog_record_id": str(blog_id),
                    "policy_event_id": policy["id"], "publication_lane": "trends_auto", "publication_mode": policy["publication_mode"],
                    "content_policy": "trends-post-edit-1", "claims_promoted": False,
                    "unverified_claim_count": sum(c.get("verification_status") == "unverified" for c in item["claims"] or []),
                    "idempotency_key": key, "public_write_performed": False,
                })
                if policy["publication_mode"] == "draft":
                    continue
                conn.execute(
                    """INSERT INTO post_publication_reviews(publishing_job_id,blog_id,content_version_id,
                    import_id,content_id,review_notes) VALUES(%s,%s,%s,%s,%s,'Trends auto publication follow-up review')
                    ON CONFLICT(publishing_job_id) WHERE publishing_job_id IS NOT NULL DO NOTHING""",
                    (job["id"], blog_id, item["content_version_id"], item["id"], item["external_content_id"]),
                )
    return {"created": created, "held": held}


def _record_hold(conn: Any, item: Any, blog_id: UUID, reasons: list[str], job_id: UUID | None = None) -> None:
    event = "publication.auto_failure.cleared" if job_id else "publication.auto_failure.recorded"
    codes = sorted(set(reasons))
    previous = conn.execute(
        """SELECT event_type,payload FROM audit_events WHERE event_type IN
        ('publication.auto_failure.recorded','publication.auto_failure.cleared')
        AND payload->>'import_id'=%s AND payload->>'content_version_id'=%s
        AND payload->>'blog_record_id'=%s ORDER BY id DESC LIMIT 1""",
        (str(item["id"]), str(item.get("content_version_id") or ""), str(blog_id)),
    ).fetchone()
    if previous and previous["event_type"] == event:
        prior = previous["payload"]
        if (prior.get("reason_codes") == codes
                and prior.get("stage") == ("queued" if job_id else "eligibility")):
            return
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES(%s,%s)",
        (event, Jsonb({"import_id": str(item["id"]), "content_version_id": str(item.get("content_version_id") or ""),
          "blog_record_id": str(blog_id), "stage": "queued" if job_id else "eligibility",
          "reason_codes": codes, "failure_reason_code": codes[0] if codes else None,
          "job_id": str(job_id) if job_id else None, "manual_publication_available": True,
          "occurred_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()})))


def _append_audit(conn: Any, event: str, payload: dict[str, Any]) -> None:
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES(%s,%s)", (event, Jsonb(payload)))
