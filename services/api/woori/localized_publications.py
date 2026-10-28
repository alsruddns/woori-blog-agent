"""Fail-closed, audited requests to extend an article into another language.

This module records a user's intent only. It does not call an AI provider or Blogger.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ai import PRODUCTION_GENERATOR_CONFIGURED
from .config import settings
from .db import connection
from .publication_modes import resolve_mode
from .publications import _mode_settings

router = APIRouter(prefix="/admin/research/localized-publications")

REGION_LANGUAGE = {"KR": "ko", "US": "en", "JP": "ja", "CN": "zh-CN"}


class TargetSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    language_code: str = Field(min_length=2, max_length=35)
    blog_id: UUID
    selection_reason: str = Field(min_length=10, max_length=1000)


class LocalizedRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evaluation_id: UUID
    source_content_version_id: UUID
    targets: list[TargetSelection] = Field(min_length=1, max_length=4)
    requester: str = Field(min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=12, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    explicit_confirmation: bool
    one_time_auto_publish_requested: bool = False

    @model_validator(mode="after")
    def target_pairs_are_unique(self) -> LocalizedRequestInput:
        pairs = [(item.language_code, item.blog_id) for item in self.targets]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate_language_blog_target")
        if not self.explicit_confirmation:
            raise ValueError("explicit_confirmation_required")
        return self


class LocalizedCancellationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    actor: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=10, max_length=1000)
    idempotency_key: str = Field(min_length=12, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


def recommended_language(region: str | None) -> tuple[str | None, str]:
    """Only map unambiguous region codes; TW/HK/SG require an editorial choice."""
    normalized = (region or "").strip().upper()
    if normalized in REGION_LANGUAGE:
        return REGION_LANGUAGE[normalized], "direct_region_language_match"
    if normalized in {"TW", "HK", "SG"}:
        return None, "regional_language_and_reader_relevance_require_editorial_selection"
    return None, "no_automatic_language_recommendation"


def _evaluation_source(evaluation_id: UUID, version_id: UUID) -> dict[str, Any]:
    url = settings().evaluation_database_url
    if not url:
        raise HTTPException(503, "Isolated evaluation source is unavailable")
    try:
        with psycopg.connect(url, connect_timeout=3, row_factory=dict_row) as conn:
            identity = conn.execute(
                "SELECT current_database() AS database_name,current_user AS role_name"
            ).fetchone()
            if not identity or identity["database_name"] != "woori_blog_agent_eval" or identity["role_name"] != "woori_eval_reader":
                raise HTTPException(503, "Evaluation database identity check failed")
            row = conn.execute(
                """SELECT id,content_version_id,language_code,machine_passed,status,
                    source_ids,fact_ids,publish_ready FROM article_quality_evaluations
                WHERE id=%s AND content_version_id=%s""",
                (evaluation_id, version_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Source manuscript evaluation not found")
            result = dict(row)
            result["source_count"] = len(result.get("source_ids") or [])
            result["fact_count"] = len(result.get("fact_ids") or [])
            return result
    except psycopg.Error:
        raise HTTPException(503, "Isolated evaluation source is unavailable") from None


def _source_context(
    conn: Any, evaluation_id: UUID, version_id: UUID,
) -> dict[str, Any]:
    evaluation = _evaluation_source(evaluation_id, version_id)
    row = conn.execute(
        """SELECT v.id AS content_version_id,v.group_id,v.localization_id,v.version,v.title,v.body,
            l.language_code AS source_language,l.target_country,
            EXISTS(SELECT 1 FROM generation_results gr JOIN generation_jobs gj
                ON gj.run_id=gr.run_id
                WHERE gr.content_version_id=v.id AND gj.evaluation_only) AS evaluation_only,
            EXISTS(SELECT 1 FROM generation_results gr JOIN generation_jobs gj
                ON gj.run_id=gr.run_id
                WHERE gr.content_version_id=v.id AND NOT gj.evaluation_only) AS operational_generation,
            EXISTS(SELECT 1 FROM publishing_records pr WHERE pr.content_version_id=v.id) AS has_published_record
        FROM content_versions v JOIN content_localizations l ON l.id=v.localization_id
        WHERE v.id=%s""",
        (version_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Source content version is unavailable in the operations store")
    source = dict(row)
    if str(source["source_language"]) != str(evaluation["language_code"]):
        raise HTTPException(409, "Source language does not match its evaluation")
    source["evaluation"] = evaluation
    source["source_body_sha256"] = hashlib.sha256(str(source["body"]).encode("utf-8")).hexdigest()
    source["source_is_evaluation_only"] = bool(source["evaluation_only"])
    source["source_provenance_verified"] = bool(source["operational_generation"] or source["has_published_record"])
    return source


def _target_versions(conn: Any, group_id: UUID, language_code: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        """SELECT v.id AS content_version_id,v.version,v.title,
            EXISTS(SELECT 1 FROM publishing_records pr WHERE pr.content_version_id=v.id) AS published
        FROM content_versions v JOIN content_localizations l ON l.id=v.localization_id
        WHERE l.group_id=%s AND l.language_code=%s ORDER BY v.version DESC,v.id""",
        (group_id, language_code),
    ).fetchall()]


def _target_plan(conn: Any, source: dict[str, Any]) -> dict[str, Any]:
    mode_state = _mode_settings(conn)
    modes = mode_state["settings"]
    languages = conn.execute(
        "SELECT code,display_name FROM languages WHERE active ORDER BY code"
    ).fetchall()
    blogs = conn.execute(
        """SELECT b.id,b.language_code,b.url,b.display_name,b.blog_id
        FROM blogger_blogs b JOIN languages l ON l.code=b.language_code
        WHERE b.active AND l.active ORDER BY b.language_code,b.display_name,b.url"""
    ).fetchall()
    recommendation, recommendation_reason = recommended_language(source.get("target_country"))
    items: list[dict[str, Any]] = []
    for language in languages:
        language_code = str(language["code"])
        existing_versions = _target_versions(conn, source["group_id"], language_code)
        for blog in blogs:
            if blog["language_code"] != language_code or language_code == source["source_language"]:
                continue
            existing_posts = conn.execute(
                """SELECT pr.remote_post_id,pr.published_at,b.url
                FROM publishing_records pr JOIN blogger_blogs b ON b.id=pr.blog_id
                JOIN content_versions pv ON pv.id=pr.content_version_id
                JOIN content_localizations pl ON pl.id=pv.localization_id
                WHERE pl.group_id=%s AND pl.language_code=%s AND pr.blog_id=%s
                ORDER BY pr.published_at DESC""",
                (source["group_id"], language_code, blog["id"]),
            ).fetchall()
            selected_mode = resolve_mode(modes, language_code, str(blog["id"]))
            items.append({
                "language_code": language_code,
                "language_name": language["display_name"],
                "blog_id": str(blog["id"]),
                "blogger_blog_id": str(blog["blog_id"]) if blog["blog_id"] else None,
                "blog_url": blog["url"],
                "blog_name": blog["display_name"],
                "publication_mode": selected_mode["configured_mode"],
                "recommended": language_code == recommendation,
                "recommendation_reason": recommendation_reason,
                "existing_localization": existing_versions[0] if existing_versions else None,
                "already_published": bool(existing_posts),
                "published_posts": [dict(post) for post in existing_posts],
            })
    requests = conn.execute(
        """SELECT r.id,r.target_language_code,r.target_blog_id,r.initial_state,
            r.publication_mode_at_request,r.one_time_auto_publish_requested,r.created_at,
            e.state AS latest_state,e.reason AS latest_reason
        FROM localized_publication_requests r LEFT JOIN LATERAL (
            SELECT state,reason FROM localized_publication_request_events
            WHERE request_id=r.id ORDER BY created_at DESC,id DESC LIMIT 1
        ) e ON true WHERE r.source_group_id=%s ORDER BY r.created_at DESC,r.id DESC""",
        (source["group_id"],),
    ).fetchall()
    languages_without_active_blog = [
        {
            "language_code": str(language["code"]),
            "language_name": language["display_name"],
            "reason": "no_active_language_blog_mapping",
        }
        for language in languages
        if language["code"] != source["source_language"]
        and not any(blog["language_code"] == language["code"] for blog in blogs)
    ]
    return {
        "source": {
            "content_version_id": str(source["content_version_id"]),
            "source_language": source["source_language"],
            "target_country": source["target_country"],
            "evaluation_only": source["source_is_evaluation_only"],
            "provenance_verified": source["source_provenance_verified"],
            "machine_passed": bool(source["evaluation"]["machine_passed"]),
            "publish_ready": bool(source["evaluation"].get("publish_ready")),
            "source_count": source["evaluation"]["source_count"],
            "fact_count": source["evaluation"]["fact_count"],
        },
        "targets": items,
        "languages_without_active_blog": languages_without_active_blog,
        "requests": [dict(row) for row in requests],
        "generation_provider_available": PRODUCTION_GENERATOR_CONFIGURED,
        "live_blogger_writes_enabled": False,
        "automatic_publishing_enabled": False,
    }


@router.get("/targets/{evaluation_id}/{content_version_id}")
def localized_publication_targets(evaluation_id: UUID, content_version_id: UUID) -> dict[str, Any]:
    with connection() as conn:
        source = _source_context(conn, evaluation_id, content_version_id)
        return _target_plan(conn, source)


def _initial_state(source: dict[str, Any], existing: list[dict[str, Any]]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    evaluation = source["evaluation"]
    if source["source_is_evaluation_only"]:
        blockers.append("source_is_evaluation_only")
        return "blocked_evaluation_only", blockers
    if not source["source_provenance_verified"]:
        blockers.append("source_provenance_unverified")
        return "blocked_source_provenance_unverified", blockers
    if not evaluation["machine_passed"]:
        blockers.append("source_quality_gate_not_passed")
        return "blocked_source_quality", blockers
    if existing:
        blockers.append("target_language_localization_already_exists")
        return "existing_localization_requires_review", blockers
    blockers.append("generation_provider_unavailable")
    return "awaiting_provider", blockers


@router.post("/requests", status_code=201)
def create_localized_publication_requests(request: LocalizedRequestInput) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    with connection() as conn:
        source = _source_context(conn, request.evaluation_id, request.source_content_version_id)
        mode_state = _mode_settings(conn)
        if mode_state["migration_required"]:
            raise HTTPException(409, "Publication settings migration 042 is required")
        plan = _target_plan(conn, source)
        selected_pairs = {(item.language_code, str(item.blog_id)) for item in request.targets}
        selection_reasons = {
            (item.language_code, str(item.blog_id)): item.selection_reason for item in request.targets
        }
        candidate_decisions: list[dict[str, Any]] = []
        for candidate in plan["targets"]:
            selected = (candidate["language_code"], candidate["blog_id"]) in selected_pairs
            if candidate["already_published"]:
                decision_reason = "already_published_target"
            elif candidate["existing_localization"]:
                decision_reason = "existing_localization_requires_editorial_review"
            elif selected:
                decision_reason = "explicitly_selected_by_user"
            else:
                decision_reason = "not_selected_by_user"
            candidate_decisions.append({
                "language_code": candidate["language_code"],
                "target_blog_id": candidate["blog_id"],
                "recommended": candidate["recommended"],
                "recommendation_reason": candidate["recommendation_reason"],
                "selected": selected,
                "decision_reason": decision_reason,
                "selection_reason": selection_reasons.get((candidate["language_code"], candidate["blog_id"])),
            })
        candidate_decisions.extend({
            "language_code": item["language_code"], "target_blog_id": None,
            "recommended": False, "selected": False, "decision_reason": item["reason"],
        } for item in plan["languages_without_active_blog"])
        for index, target in enumerate(request.targets):
            blog = conn.execute(
                """SELECT id,language_code,active FROM blogger_blogs
                WHERE id=%s AND active""", (target.blog_id,),
            ).fetchone()
            if not blog or blog["language_code"] != target.language_code:
                raise HTTPException(422, "Selected language does not match an active registered Blogger blog")
            if target.language_code == source["source_language"]:
                raise HTTPException(422, "Source language cannot be selected as an additional language")
            existing_posts = conn.execute(
                """SELECT pr.remote_post_id,pr.published_at,b.url
                FROM publishing_records pr JOIN blogger_blogs b ON b.id=pr.blog_id
                JOIN content_versions pv ON pv.id=pr.content_version_id
                JOIN content_localizations pl ON pl.id=pv.localization_id
                WHERE pl.group_id=%s AND pl.language_code=%s AND pr.blog_id=%s LIMIT 1""",
                (source["group_id"], target.language_code, target.blog_id),
            ).fetchone()
            if existing_posts:
                created.append({
                    "language_code": target.language_code, "blog_id": str(target.blog_id),
                    "state": "already_published", "duplicate": True,
                    "published_post": dict(existing_posts), "provider_called": False,
                    "blogger_write_performed": False,
                })
                continue

            existing_versions = _target_versions(conn, source["group_id"], target.language_code)
            state, blockers = _initial_state(source, existing_versions)
            selected_mode = resolve_mode(mode_state["settings"], target.language_code, str(target.blog_id))
            if selected_mode["configured_mode"] == "auto":
                blockers.extend(["live_auto_not_approved", "live_blogger_writes_disabled"])
            if not PRODUCTION_GENERATOR_CONFIGURED:
                blockers.append("generation_provider_unavailable")
            if not source["evaluation"]["publish_ready"]:
                blockers.append("publication_readiness_not_verified")
            request_idempotency = f"{request.idempotency_key}_{index}_{target.language_code.replace('-', '_')}"
            if len(request_idempotency) > 160:
                request_idempotency = hashlib.sha256(request_idempotency.encode()).hexdigest()
            event_key = f"{request_idempotency}_event"
            if len(event_key) > 160:
                event_key = hashlib.sha256(event_key.encode()).hexdigest()
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (
                f"localized:{source['group_id']}:{target.language_code}:{target.blog_id}",
            ))
            active = conn.execute(
                """SELECT r.id,r.initial_state,r.created_at,
                    COALESCE(e.state,r.initial_state) AS latest_state
                FROM localized_publication_requests r LEFT JOIN LATERAL (
                    SELECT state FROM localized_publication_request_events
                    WHERE request_id=r.id ORDER BY created_at DESC,id DESC LIMIT 1
                ) e ON true
                WHERE r.source_group_id=%s AND r.target_language_code=%s AND r.target_blog_id=%s
                ORDER BY r.created_at DESC,r.id DESC LIMIT 1""",
                (source["group_id"], target.language_code, target.blog_id),
            ).fetchone()
            if active and active["latest_state"] not in {"cancelled", "published"}:
                created.append({
                    "request_id": str(active["id"]), "language_code": target.language_code,
                    "blog_id": str(target.blog_id), "state": active["latest_state"],
                    "duplicate": True, "provider_called": False,
                    "blogger_write_performed": False, "publish_ready": False,
                })
                continue
            row = conn.execute(
                """INSERT INTO localized_publication_requests(
                    source_evaluation_id,source_content_version_id,source_localization_id,source_group_id,
                    source_language_code,source_body_sha256,target_language_code,target_blog_id,requested_by,
                    idempotency_key,publication_mode_at_request,one_time_auto_publish_requested,
                    initial_state,existing_target_content_version_id,blockers)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING id,initial_state,created_at""",
                (
                    request.evaluation_id, request.source_content_version_id, source["localization_id"],
                    source["group_id"], source["source_language"], source["source_body_sha256"],
                    target.language_code, target.blog_id, request.requester, request_idempotency,
                    selected_mode["configured_mode"], request.one_time_auto_publish_requested, state,
                    existing_versions[0]["content_version_id"] if existing_versions else None, Jsonb(blockers),
                ),
            ).fetchone()
            duplicate = row is None
            if duplicate:
                row = conn.execute(
                    """SELECT id,initial_state,created_at FROM localized_publication_requests
                    WHERE idempotency_key=%s""",
                    (request_idempotency,),
                ).fetchone()
                if row is None:
                    raise HTTPException(409, "Idempotency key is already associated with another request")
            else:
                assert row is not None
                conn.execute(
                    """INSERT INTO localized_publication_request_events(
                        request_id,event_key,event_type,state,actor,reason,details)
                    VALUES (%s,%s,'requested',%s,%s,%s,%s)""",
                    (row["id"], event_key, state, request.requester,
                     "User explicitly requested a language-specific editorial extension.",
                     Jsonb({"evaluation_id": str(request.evaluation_id),
                         "source_content_version_id": str(request.source_content_version_id),
                         "source_body_sha256": source["source_body_sha256"],
                         "target_language": target.language_code, "target_blog_id": str(target.blog_id),
                         "source_region": source.get("target_country"),
                         "candidate_language_decisions": candidate_decisions,
                         "publication_mode": selected_mode["configured_mode"],
                         "one_time_auto_publish_requested": request.one_time_auto_publish_requested,
                         "blockers": blockers, "provider_called": False,
                         "blogger_write_performed": False}),),
                )
                conn.execute(
                    """INSERT INTO audit_events(event_type,blog_id,payload)
                    VALUES ('localized_publication.requested',%s,%s)""",
                    (target.blog_id, Jsonb({"request_id": str(row["id"]),
                        "source_content_version_id": str(request.source_content_version_id),
                        "source_group_id": str(source["group_id"]),
                        "target_language": target.language_code, "state": state,
                        "source_region": source.get("target_country"),
                        "candidate_language_decisions": candidate_decisions,
                        "publication_mode": selected_mode["configured_mode"],
                        "one_time_auto_publish_requested": request.one_time_auto_publish_requested,
                        "provider_called": False, "blogger_write_performed": False})),
                )
            assert row is not None
            created.append({
                "request_id": str(row["id"]), "language_code": target.language_code,
                "blog_id": str(target.blog_id), "state": row["initial_state"],
                "duplicate": duplicate, "blockers": blockers,
                "publication_mode": selected_mode["configured_mode"],
                "one_time_auto_publish_requested": request.one_time_auto_publish_requested,
                "provider_called": False, "blogger_write_performed": False,
                "publish_ready": False,
            })
    return {
        "items": created,
        "generation_provider_available": PRODUCTION_GENERATOR_CONFIGURED,
        "live_blogger_writes_enabled": False,
        "automatic_publishing_enabled": False,
        "publish_ready": False,
    }


@router.post("/requests/{request_id}/cancel")
def cancel_localized_publication_request(
    request_id: UUID, request: LocalizedCancellationInput,
) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """SELECT id,source_group_id,target_language_code,target_blog_id,initial_state
            FROM localized_publication_requests WHERE id=%s""", (request_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Localized publication request not found")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (
            f"localized:{row['source_group_id']}:{row['target_language_code']}:{row['target_blog_id']}",
        ))
        latest = conn.execute(
            """SELECT state FROM localized_publication_request_events
            WHERE request_id=%s ORDER BY created_at DESC,id DESC LIMIT 1""", (request_id,),
        ).fetchone()
        current_state = str(latest["state"] if latest else row["initial_state"])
        if current_state in {"cancelled", "published"}:
            return {"request_id": str(request_id), "state": current_state, "duplicate": True,
                    "provider_called": False, "blogger_write_performed": False}
        inserted = conn.execute(
            """INSERT INTO localized_publication_request_events(
                request_id,event_key,event_type,state,actor,reason,details)
            VALUES (%s,%s,'cancelled','cancelled',%s,%s,%s)
            ON CONFLICT(event_key) DO NOTHING RETURNING id""",
            (request_id, request.idempotency_key, request.actor, request.reason,
             Jsonb({"previous_state": current_state, "provider_called": False,
                    "blogger_write_performed": False})),
        ).fetchone()
        if not inserted:
            existing_event = conn.execute(
                "SELECT request_id,event_type FROM localized_publication_request_events WHERE event_key=%s",
                (request.idempotency_key,),
            ).fetchone()
            if existing_event and existing_event["request_id"] == request_id and existing_event["event_type"] == "cancelled":
                return {"request_id": str(request_id), "state": "cancelled", "duplicate": True,
                        "provider_called": False, "blogger_write_performed": False}
            raise HTTPException(409, "Cancellation idempotency key is already used")
        conn.execute(
            """INSERT INTO audit_events(event_type,blog_id,payload)
            VALUES ('localized_publication.cancelled',%s,%s)""",
            (row["target_blog_id"], Jsonb({"request_id": str(request_id),
                "target_language": row["target_language_code"], "previous_state": current_state,
                "actor": request.actor, "reason": request.reason,
                "provider_called": False, "blogger_write_performed": False})),
        )
        return {"request_id": str(request_id), "state": "cancelled", "duplicate": False,
                "provider_called": False, "blogger_write_performed": False, "publish_ready": False}
