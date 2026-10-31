"""Fail-closed publication requests and explicitly offline mock simulations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import blogger_service, external_policy
from .blogger_writes import BloggerLivePublisher
from .content_representatives import same_manuscript_content
from .db import connection
from .google_http import GoogleFailure
from .publication_daily import (
    GLOBAL_DAILY_PUBLISH_LIMIT,
    LANGUAGE_DAILY_LIMITS,
    LANGUAGE_HOURLY_LIMITS,
)
from .publication_modes import (
    ModeSettingsInput,
    effective_mode,
    resolve_mode,
)

router = APIRouter(prefix="/admin/publications")


def _live_write_capability(
    conn: Any, policy: dict[str, Any], heartbeat: dict[str, Any] | None,
    emergency_stopped: bool,
) -> dict[str, Any]:
    """Report only live lanes the current heartbeat and scoped policies can dispatch."""
    fresh = bool(heartbeat and heartbeat.get("status") == "running" and heartbeat.get("last_seen_at")
                 and datetime.now(UTC) - heartbeat["last_seen_at"] <= timedelta(seconds=45))
    mode = heartbeat.get("execution_mode") if heartbeat else None
    scheduled_worker = fresh and mode in {
        "operations-scheduled-auto", "operations-scheduled-auto-and-manual",
        "operations-scheduled-auto-and-manual-and-trends"
    }
    manual_worker = fresh and mode in {
        "operations-manual-confirmed", "operations-scheduled-auto-and-manual",
        "operations-scheduled-auto-and-manual-and-trends"
    }
    trends_worker = fresh and mode == "operations-scheduled-auto-and-manual-and-trends"
    owner_policy = external_policy._blogger_policy_approval() is not None
    no_billable_credentials = not external_policy.billing_credential_names()
    approved = [str(value) for value in (policy.get("policy_event") or {}).get("approved_blog_ids", [])]
    mapped = conn.execute(
        """SELECT count(*)::int AS n FROM blogger_blogs b JOIN google_connections g
        ON g.id=b.oauth_connection_id WHERE b.id=ANY(%s::uuid[]) AND b.active
          AND g.status='connected' AND g.scopes=ARRAY['https://www.googleapis.com/auth/blogger']::text[]""",
        (approved,),
    ).fetchone()["n"] if approved else 0
    scheduled = bool(policy.get("enabled") and approved and mapped == len(set(approved))
                     and owner_policy and scheduled_worker and not emergency_stopped
                     and no_billable_credentials)
    manual = bool(owner_policy and manual_worker and not emergency_stopped and no_billable_credentials)
    trends_policies = conn.execute(
        """SELECT DISTINCT ON(p.blog_id) p.blog_id,p.enabled,p.allowed_geos,b.active,
          b.oauth_connection_id,g.status AS oauth_status,g.scopes
        FROM trends_publication_policy_events p JOIN blogger_blogs b ON b.id=p.blog_id
        LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        ORDER BY p.blog_id,p.id DESC"""
    ).fetchall()
    trends = bool(owner_policy and external_policy._blogger_public_publish_approval()
                  and trends_worker and not emergency_stopped and no_billable_credentials
                  and any(p["enabled"] and p["allowed_geos"] and p["active"]
                          and p["oauth_status"] == "connected"
                          and list(p["scopes"] or []) == ["https://www.googleapis.com/auth/blogger"]
                          for p in trends_policies))
    reason = None
    if not (scheduled or manual or trends):
        if not fresh or not mode:
            reason = "worker_heartbeat_stale_or_mode_missing"
        elif not owner_policy:
            reason = "blogger_owner_policy_missing"
        elif emergency_stopped:
            reason = "global_emergency_stop_active"
        elif not no_billable_credentials:
            reason = "external_billing_credential_present"
        elif policy.get("enabled") and approved and mapped != len(set(approved)):
            reason = "scheduled_blog_or_oauth_scope_unavailable"
        else:
            reason = "worker_mode_or_scheduled_policy_not_enabled"
    return {"scheduled_auto": scheduled, "manual_confirmed": manual, "trends_auto": trends,
            "live_dispatch": bool(scheduled_worker or manual_worker),
            "reason": reason, "worker_fresh": fresh, "execution_mode": mode}

PublicationState = Literal[
    "draft",
    "quality_held",
    "machine_checked",
    "human_review_pending",
    "human_review_rejected",
    "human_review_approved",
    "publication_blocked",
    "publication_queued",
    "publishing",
    "published",
    "publication_failed",
    "cancelled",
]


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content_version_id: UUID
    blog_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ManualLiveRequestInput(BaseModel):
    """Explicit user authorization for one immutable manual manuscript payload."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content_version_id: UUID
    blog_id: UUID
    expected_title_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_label: str = Field(min_length=2, max_length=120)
    # A concise reason such as "확인완료" is sufficient alongside the exact
    # content hashes and the three explicit safety attestations recorded below.
    reason: str = Field(min_length=3, max_length=2000)
    reviewed_exact_content: Literal[True]
    assertions_safe_to_publish: Literal[True]
    rights_privacy_harm_checked: Literal[True]
    confirmation: Literal["PUBLISH THIS EXACT MANUSCRIPT PUBLICLY"]
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class TrendsAutoPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    blog_id: UUID
    enabled: bool
    publication_mode: Literal["draft", "publish"] = "draft"
    allowed_geos: list[str] = Field(default_factory=list, max_length=11)
    daily_limit: int | None = Field(default=None, ge=1, le=10)
    actor_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    confirmation: str = ""

    @model_validator(mode="after")
    def action_confirmation_matches(self) -> TrendsAutoPolicyInput:
        expected = "ENABLE TRENDS AUTO PUBLICATION" if self.enabled else "STOP TRENDS AUTO PUBLICATION"
        if self.publication_mode == "publish" and self.confirmation != expected:
            raise ValueError("explicit_trends_publication_confirmation_required")
        if any(value not in {"KR","US","GB","CA","AU","IN","JP","TW","HK","SG","PH","BR"}
               for value in self.allowed_geos):
            raise ValueError("unsupported_trends_geography")
        if len(set(self.allowed_geos)) != len(self.allowed_geos):
            raise ValueError("duplicate_trends_geography")
        return self


@router.get("/trends-auto-policy")
def get_trends_auto_policy() -> dict[str, Any]:
    from .trends_publication import policy_state
    with connection() as conn:
        return policy_state(conn)


@router.post("/trends-auto-policy", status_code=201)
def save_trends_auto_policy(request: TrendsAutoPolicyInput) -> dict[str, Any]:
    from .trends_publication import record_policy
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('trends-publication-policy',0))")
        result = record_policy(conn, request)
        return result


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    scenario: Literal["success", "timeout", "auth_failure", "server_failure", "uncertain"]


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    scheduled_at: datetime
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)
    mock_scenario: Literal["success", "timeout", "auth_failure", "server_failure", "uncertain"] = (
        "success"
    )

    @model_validator(mode="after")
    def valid_schedule(self) -> ScheduleInput:
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at_requires_timezone")
        if self.scheduled_at.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("schedule_must_be_in_future")
        try:
            expected_offset = self.scheduled_at.astimezone(ZoneInfo(self.timezone)).utcoffset()
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid_schedule_timezone") from None
        if self.scheduled_at.utcoffset() != expected_offset:
            raise ValueError("scheduled_at_offset_does_not_match_timezone")
        return self


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class EmergencyStopInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Literal[True]


class ScheduledAutoPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["enable", "disable"]
    blog_ids: list[UUID] = Field(default_factory=list, min_length=0, max_length=4)
    daily_limit: int = Field(default=1, ge=1, le=3)
    actor_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    confirmation: str

    @model_validator(mode="after")
    def explicit_confirmation(self) -> ScheduledAutoPolicyInput:
        expected = "ENABLE SCHEDULED AUTO PUBLICATION" if self.action == "enable" else "STOP SCHEDULED AUTO PUBLICATION"
        if self.confirmation != expected:
            raise ValueError("explicit_scheduled_publication_confirmation_required")
        return self


class ScheduledFirstPostApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    blog_id: UUID
    import_id: UUID
    import_version_id: UUID
    content_version_id: UUID
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    confirmation: Literal["APPROVE THIS SCHEDULED MANUSCRIPT FOR FIRST PUBLICATION"]


class ScheduledConnectionCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blog_ids: list[UUID] = Field(min_length=1, max_length=4)


class PostPublicationReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    review_status: Literal["pending", "in_progress", "completed"]
    review_notes: str = Field(default="", max_length=4000)


class PostPublicationReviewItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    issue_type: Literal["exchange_rate", "source", "number", "date", "translation", "copyright", "other"]
    severity: Literal["low", "medium", "high"]
    description: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def _mode_settings(conn: Any) -> dict[str, Any]:
    relation = conn.execute(
        "SELECT to_regclass('public.publication_mode_settings') AS table_name"
    ).fetchone()
    if not relation or not relation["table_name"]:
        return {
            "migration_required": True,
            "default_mode": "manual",
            "settings": [],
            "languages": [],
            "blogs": [],
            "emergency_stopped": False,
            "operations_auto_approved": False,
            "live_auto_enabled": False,
            "real_writes_enabled": False,
            "scheduled_auto_policy": {"enabled": False, "migration_required": True,
                                      "trends_lane_affected": False},
            "scoped_write_capability": {"scheduled_auto": False, "manual_confirmed": False},
        }
    rows = conn.execute(
        """SELECT scope_type,scope_key,configured_mode,daily_auto_limit,
            minimum_interval_minutes,allowed_start_hour,allowed_end_hour,timezone,
            allowed_categories,excluded_topics,max_source_age_hours,retry_limit,
            emergency_stopped,operations_auto_approved,updated_at
        FROM publication_mode_settings ORDER BY CASE scope_type WHEN 'global' THEN 0
            WHEN 'language' THEN 1 ELSE 2 END,scope_key"""
    ).fetchall()
    scheduled_table = conn.execute(
        "SELECT to_regclass('public.scheduled_publication_policy_events') AS table_name"
    ).fetchone()
    items = [dict(row) for row in rows]
    languages = [dict(row) for row in conn.execute(
        "SELECT code,display_name,active FROM languages ORDER BY code"
    ).fetchall()]
    blogs = [dict(row) for row in conn.execute(
        "SELECT id,language_code,url,display_name,active FROM blogger_blogs ORDER BY language_code,url"
    ).fetchall()]
    global_setting = next((row for row in items if row["scope_type"] == "global"), None)
    scheduled = _scheduled_auto_state(conn) if scheduled_table and scheduled_table["table_name"] else {
        "enabled": False, "migration_required": True, "trends_lane_affected": False
    }
    heartbeat_row = conn.execute(
        "SELECT status,last_seen_at,execution_mode FROM worker_heartbeats WHERE service_name='publication_worker'"
    ).fetchone()
    capability = _live_write_capability(
        conn, scheduled, dict(heartbeat_row) if heartbeat_row else None,
        bool(global_setting and global_setting["emergency_stopped"]),
    )
    return {
        "migration_required": False,
        "default_mode": "manual",
        "settings": items,
        "languages": languages,
        "blogs": blogs,
        "emergency_stopped": bool(global_setting and global_setting["emergency_stopped"]),
        "operations_auto_approved": False,
        "live_auto_enabled": capability["scheduled_auto"],
        "real_writes_enabled": bool(capability["scheduled_auto"] or capability["manual_confirmed"]),
        "scoped_write_capability": {"scheduled_auto": capability["scheduled_auto"],
                                    "manual_confirmed": capability["manual_confirmed"],
                                    "reason": capability["reason"]},
        "scheduled_auto_policy": scheduled,
        "publication_worker": dict(heartbeat_row) if heartbeat_row else None,
    }


def _blog_settings(conn: Any, blog_id: str) -> tuple[dict[str, Any] | None, str | None]:
    blog = conn.execute(
        "SELECT id,language_code FROM blogger_blogs WHERE id=%s AND active", (blog_id,)
    ).fetchone()
    if not blog:
        return None, "blog_not_found_or_inactive"
    return dict(blog), None


@router.get("/mode-settings")
def get_mode_settings() -> dict[str, Any]:
    with connection() as conn:
        return _mode_settings(conn)


def _scheduled_auto_state(conn: Any) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id,action,approved_blog_ids,daily_limit,actor_label,reason,created_at
        FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    enabled = bool(row and row["action"] == "enabled")
    first_post = conn.execute(
        """SELECT e.id,e.blog_id,e.import_id,e.import_version_id,e.content_version_id,
        e.body_sha256,e.actor_label,e.created_at FROM scheduled_first_publication_events e
        WHERE e.action='approved' AND NOT EXISTS (
          SELECT 1 FROM scheduled_first_publication_events r
          WHERE r.action='revoked' AND r.blog_id=e.blog_id AND r.import_id=e.import_id
            AND r.import_version_id=e.import_version_id AND r.content_version_id=e.content_version_id
            AND r.body_sha256=e.body_sha256 AND r.id>e.id)
        ORDER BY e.id DESC LIMIT 1"""
    ).fetchone()
    published = conn.execute(
        """SELECT EXISTS(SELECT 1 FROM publishing_jobs WHERE publication_lane='scheduled_auto'
          AND status='succeeded') AS any_published"""
    ).fetchone()["any_published"]
    policy_history = conn.execute(
        """SELECT id,action,approved_blog_ids,daily_limit,actor_label,reason,created_at
        FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 20"""
    ).fetchall()
    first_post_history = conn.execute(
        """SELECT id,action,blog_id,import_id,import_version_id,content_version_id,
        body_sha256,actor_label,reason,created_at FROM scheduled_first_publication_events
        ORDER BY id DESC LIMIT 20"""
    ).fetchall()
    connection_check = conn.execute(
        """SELECT payload,created_at FROM audit_events
        WHERE event_type='publication.scheduled_auto.connection_check'
        ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    return {
        "enabled": enabled,
        "policy_event": dict(row) if row else None,
        "first_post_approval": dict(first_post) if first_post else None,
        "first_post_confirmed": bool(published),
        "policy_history": [dict(item) for item in policy_history],
        "first_post_history": [dict(item) for item in first_post_history],
        "latest_connection_check": dict(connection_check) if connection_check else None,
        "first_publication_approval_required": False,
        "legacy_first_post_history_only": True,
        "effective_for_new_jobs": enabled,
        "trends_lane_affected": False,
    }


@router.get("/scheduled-auto-policy")
def get_scheduled_auto_policy() -> dict[str, Any]:
    with connection() as conn:
        return _scheduled_auto_state(conn)


@router.post("/scheduled-auto-policy", status_code=201)
def record_scheduled_auto_policy(request: ScheduledAutoPolicyInput) -> dict[str, Any]:
    """Record explicit admin approval for scheduled exports only; defaults stay OFF."""
    expected = (
        "ENABLE SCHEDULED AUTO PUBLICATION" if request.action == "enable"
        else "STOP SCHEDULED AUTO PUBLICATION"
    )
    if request.confirmation != expected:
        raise HTTPException(422, "Explicit scheduled publication confirmation is required")
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('scheduled-auto-policy',0))")
        prior = conn.execute(
            "SELECT id,action,approved_blog_ids,daily_limit FROM scheduled_publication_policy_events WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone()
        blog_ids = sorted({str(value) for value in request.blog_ids})
        if request.action == "enable":
            if not blog_ids:
                raise HTTPException(422, "At least one active Blogger blog must be explicitly selected")
            blogs = conn.execute(
                """SELECT b.id,b.language_code,b.blog_id,b.oauth_connection_id,g.status,g.scopes
                FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
                WHERE b.id=ANY(%s::uuid[]) AND b.active ORDER BY b.id""",
                (blog_ids,),
            ).fetchall()
            if len(blogs) != len(blog_ids):
                raise HTTPException(422, "Every selected blog must be registered and active")
            from .google_http import WRITE_SCOPE
            if any(not row["blog_id"] or row["status"] != "connected"
                   or list(row["scopes"] or []) != [WRITE_SCOPE] for row in blogs):
                raise HTTPException(409, "Selected blogs require a connected Blogger write-scope mapping")
            verification = conn.execute(
                """SELECT payload,created_at FROM audit_events
                WHERE event_type='publication.scheduled_auto.connection_check'
                ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            verified_results = {
                str(item.get("blog_record_id")): item
                for item in (verification["payload"].get("results", []) if verification else [])
                if isinstance(item, dict)
            }
            now = datetime.now(UTC)
            if not verification or verification["created_at"] < now - timedelta(hours=24):
                raise HTTPException(409, "Run a fresh Blogger read-only connection verification first")
            for blog in blogs:
                check = verified_results.get(str(blog["id"]))
                if (not check or not check.get("verified")
                        or str(check.get("remote_blog_id")) != str(blog["blog_id"])):
                    raise HTTPException(409, "Every selected blog must pass the latest Blogger read-only identity check")
        if prior:
            if (prior["action"] != ("enabled" if request.action == "enable" else "disabled")
                    or sorted(str(value) for value in prior["approved_blog_ids"]) != blog_ids):
                raise HTTPException(409, "Idempotency key conflicts with a prior policy event")
            return {"event_id": prior["id"], "duplicate": True,
                    "scheduled_auto_enabled": request.action == "enable"}
        current = _scheduled_auto_state(conn)
        if request.action == "disable":
            # Retain scope from the last enable event as immutable history.
            blog_ids = list((current.get("policy_event") or {}).get("approved_blog_ids") or [])
        previous_event = current.get("policy_event") or {}
        saved = conn.execute(
            """INSERT INTO scheduled_publication_policy_events
            (action,approved_blog_ids,daily_limit,actor_label,reason,idempotency_key)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,created_at""",
            ("enabled" if request.action == "enable" else "disabled", Jsonb(blog_ids),
             request.daily_limit, request.actor_label, request.reason, request.idempotency_key),
        ).fetchone()
        if saved is None:
            raise HTTPException(503, "Scheduled publication policy event was not persisted")
        payload = {
            "event_id": saved["id"], "action": request.action,
            "approved_blog_ids": blog_ids, "daily_limit": request.daily_limit,
            "actor_label": request.actor_label, "reason": request.reason,
            "authenticated_by": "admin_bearer", "previous_enabled": current["enabled"],
            "previous_blog_ids": list(previous_event.get("approved_blog_ids") or []),
            "previous_daily_limit": previous_event.get("daily_limit"),
            "new_enabled": request.action == "enable", "trends_lane_affected": False,
            "new_blog_ids": blog_ids, "new_daily_limit": request.daily_limit,
            "live_writes_enabled": request.action == "enable",
        }
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            ("publication.scheduled_auto." + request.action, Jsonb(payload)),
        )
        return {"event_id": saved["id"], "created_at": saved["created_at"],
                "scheduled_auto_enabled": request.action == "enable",
                "approved_blog_ids": blog_ids, "first_post_approval_required": False,
                "legacy_first_post_events_changed": False,
                "trends_lane_affected": False}


@router.post("/scheduled-auto-first-post", status_code=410)
def approve_scheduled_first_post(request: ScheduledFirstPostApprovalInput) -> dict[str, Any]:
    """Deprecated: Scheduled Auto scope no longer requires a first-post event."""
    del request
    raise HTTPException(
        status_code=410,
        detail="Scheduled first-publication approval is retired; enable the scoped Scheduled Auto policy instead.",
    )


@router.get("/scheduled-auto-state")
@router.get("/scheduled-auto-first-post")
def scheduled_first_post_status(import_id: Annotated[UUID, Query()]) -> dict[str, Any]:
    """Expose Scheduled Auto status and hard blockers; first-post approval is retired."""
    from .google_http import WRITE_SCOPE

    with connection() as conn:
        imported = conn.execute(
            """SELECT i.id,i.generation_method,i.language_code,i.title AS import_title,
                v.id AS import_version_id,v.version_number,v.title,v.body_markdown,
                v.content_sha256,link.content_version_id
            FROM external_content_imports i
            LEFT JOIN LATERAL (
              SELECT * FROM external_content_import_versions WHERE import_id=i.id
              ORDER BY version_number DESC LIMIT 1
            ) v ON true
            LEFT JOIN external_content_import_content_links link
              ON link.import_id=i.id AND link.import_version_id=v.id
            WHERE i.id=%s""",
            (import_id,),
        ).fetchone()
        if not imported:
            raise HTTPException(404, "Scheduled manuscript import was not found")

        version_id = imported.get("import_version_id")
        content_version_id = imported.get("content_version_id")
        body = str(imported.get("body_markdown") or "")
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assessment = conn.execute(
            """SELECT id,machine_passed,publish_ready,assessed_at FROM external_content_import_assessments
            WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1""",
            (import_id, version_id),
        ).fetchone() if version_id else None
        review = conn.execute(
            """SELECT event_type,reviewer_label,reason,sources_examined,claims_checked,
                rights_reviewed,created_at FROM external_content_import_review_events
            WHERE import_id=%s AND version_id=%s ORDER BY created_at DESC,id DESC LIMIT 1""",
            (import_id, version_id),
        ).fetchone() if version_id else None
        policy = _scheduled_auto_state(conn)
        policy_event = policy.get("policy_event") or {}
        approved_blog_ids = {str(value) for value in policy_event.get("approved_blog_ids", [])}
        global_setting = conn.execute(
            "SELECT emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
        ).fetchone()
        emergency_stopped = bool(global_setting and global_setting.get("emergency_stopped"))
        evidence_assessment = conn.execute(
            """SELECT payload,created_at FROM audit_events
            WHERE event_type='publication.scheduled_auto.evidence_assessed'
              AND payload->>'import_id'=%s AND payload->>'import_version_id'=%s
            ORDER BY id DESC LIMIT 1""",
            (str(import_id), str(version_id) if version_id else ""),
        ).fetchone() if version_id else None
        latest_auto_failure = conn.execute(
            """SELECT event_type,payload,id FROM audit_events
            WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
              AND payload->>'import_id'=%s AND payload->>'content_version_id'=%s
            ORDER BY id DESC LIMIT 1""",
            (str(import_id), str(content_version_id or "")),
        ).fetchone() if version_id else None

        blogs = conn.execute(
            """SELECT b.id,b.blog_id,b.language_code,b.display_name,b.url,b.active,
                b.connection_verified_at,g.status AS oauth_status,g.scopes
            FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
            WHERE b.language_code=%s ORDER BY b.active DESC,b.display_name,b.url""",
            (imported["language_code"],),
        ).fetchall()
        targets: list[dict[str, Any]] = []
        for blog in blogs:
            blog_id = str(blog["id"])
            in_scope = blog_id in approved_blog_ids
            jobs = conn.execute(
                """SELECT j.id,j.status,j.publication_state,j.scheduled_at,j.updated_at,
                    j.simulation_only,j.adapter_type,r.remote_post_id,r.remote_url,r.remote_status,
                    r.remote_verified_at,r.published_at
                FROM publishing_jobs j LEFT JOIN publishing_records r ON r.job_id=j.id
                WHERE j.content_version_id=%s AND j.blog_id=%s
                ORDER BY j.updated_at DESC,j.id DESC LIMIT 10""",
                (content_version_id, blog["id"]),
            ).fetchall() if content_version_id else []
            remote_write_policy = bool(
                external_policy._blogger_policy_approval()
                and external_policy._scheduled_publication_approval(blog_id)
            )
            blog_jobs = [dict(job) for job in jobs]
            manual_publication: dict[str, Any] = {}
            # Manual eligibility is a read model for every imported manuscript.
            # Restricting it to scheduled auto-failure events left ordinary
            # manual imports with an empty object, which the Dashboard reported
            # as an unavailable eligibility check even though this request
            # itself succeeded.
            if content_version_id:
                manual_candidate = _candidate(conn, UUID(str(content_version_id)), UUID(blog_id))
                manual_row = dict(manual_candidate) if manual_candidate else None
                manual_snapshot = _manual_publication_snapshot(conn, manual_row)
                manual_blockers = _manual_publication_blockers(
                    conn, manual_row, manual_snapshot, UUID(blog_id),
                )
                manual_publication = {
                    "status": "eligible" if not manual_blockers else "blocked",
                    "eligible": not manual_blockers,
                    "blockers": manual_blockers,
                    "title": manual_snapshot.get("title"),
                    "body": manual_snapshot.get("body"),
                    "title_sha256": manual_snapshot.get("title_sha256"),
                    "body_sha256": manual_snapshot.get("body_sha256"),
                    "html_sha256": manual_snapshot.get("html_sha256"),
                    "generation_method": manual_snapshot.get("generation_method"),
                    "content_version_id": str(content_version_id),
                    "followups": manual_snapshot.get("followups", []),
                    "oauth_write_scope": list(blog["scopes"] or []) == [WRITE_SCOPE],
                    # Manual public-write scope is created only by the user's
                    # exact-version confirmation; no global Auto setting is implied.
                    "remote_write_policy_available": external_policy._blogger_policy_approval() is not None,
                    "jobs": blog_jobs,
                }
            blockers: list[str] = []
            if imported["generation_method"] != "chatgpt_scheduled_export":
                blockers.append("not_a_codex_scheduled_export")
            if not content_version_id:
                blockers.append("scheduled_version_not_promoted")
            if not policy.get("enabled"):
                blockers.append("scheduled_auto_policy_inactive")
            if emergency_stopped:
                blockers.append("publication_emergency_stop_active")
            if not blog["active"] or not in_scope:
                blockers.append("blog_not_in_active_scheduled_scope")
            if blog["oauth_status"] != "connected" or list(blog["scopes"] or []) != [WRITE_SCOPE]:
                blockers.append("blogger_write_oauth_not_verified")
            if not remote_write_policy:
                blockers.append("scheduled_live_write_policy_not_available")
            if any(job.get("remote_post_id") and not job.get("simulation_only") for job in blog_jobs):
                blockers.append("remote_publication_already_recorded")
            targets.append({
                **dict(blog),
                "in_scheduled_scope": in_scope,
                "first_approval": None,
                "first_publication_approval_required": False,
                "approval_blockers": blockers,
                "remote_write_policy_available": remote_write_policy,
                "manual_publication": manual_publication,
                "jobs": blog_jobs,
            })

        return {
            "import_id": str(import_id),
            "generation_method": imported["generation_method"],
            "language_code": imported["language_code"],
            "title": imported["title"] or imported["import_title"],
            "import_version_id": str(version_id) if version_id else None,
            "version_number": imported.get("version_number"),
            "content_version_id": str(content_version_id) if content_version_id else None,
            "body_sha256": body_sha256,
            "assessment": dict(assessment) if assessment else None,
            "editorial_review": dict(review) if review else None,
            "evidence_assessment": {
                "status": evidence_assessment["payload"].get("status"),
                "reasons": evidence_assessment["payload"].get("reasons", []),
                "created_at": evidence_assessment["created_at"],
            } if evidence_assessment else None,
            "auto_publication_failure": bool(latest_auto_failure and
                latest_auto_failure["event_type"] == "publication.auto_failure.recorded"),
            "auto_failure": dict(latest_auto_failure["payload"]) if latest_auto_failure and
                latest_auto_failure["event_type"] == "publication.auto_failure.recorded" else None,
            "scheduled_auto_enabled": bool(policy.get("enabled")),
            "effective_for_new_jobs": bool(policy.get("effective_for_new_jobs")),
            "first_publication_approval_required": False,
            "legacy_first_post_events_are_audit_only": True,
            "emergency_stopped": emergency_stopped,
            "targets": targets,
            "publish_ready": False,
            "actual_write_performed": False,
        }


@router.post("/manual-live-requests", status_code=201)
def create_manual_live_request(request: ManualLiveRequestInput) -> dict[str, Any]:
    """Record a user's exact-version public-publish confirmation and queue a manual job."""
    with connection() as conn:
        migration = conn.execute(
            "SELECT to_regclass('public.manual_publication_approval_events') AS ready"
        ).fetchone()
        if migration is None or not migration["ready"]:
            raise HTTPException(503, "Manual Blogger publication migration 056 is required")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"manual-blogger-publish:{request.blog_id}:{request.content_version_id}",),
        )
        prior = conn.execute(
            """SELECT j.id,j.status,j.publication_state,j.adapter_type,j.simulation_only,
                a.id AS approval_event_id FROM publishing_jobs j
            LEFT JOIN manual_publication_approval_events a ON a.job_id=j.id
            WHERE j.blog_id=%s AND j.content_version_id=%s AND j.publication_lane='manual'
              AND NOT j.simulation_only AND j.adapter_type='blogger_live'
            ORDER BY j.updated_at DESC,j.id DESC LIMIT 1""",
            (request.blog_id, request.content_version_id),
        ).fetchone()
        row = _candidate(conn, request.content_version_id, request.blog_id)
        if row is None:
            raise HTTPException(404, "Content version or registered blog not found")
        row = dict(row)
        snapshot = _manual_publication_snapshot(conn, row)
        expected = (
            (request.expected_title_sha256, snapshot.get("title_sha256")),
            (request.expected_body_sha256, snapshot.get("body_sha256")),
            (request.expected_html_sha256, snapshot.get("html_sha256")),
        )
        if any(not actual or supplied != actual for supplied, actual in expected):
            raise HTTPException(409, "Manuscript changed after confirmation; reload the latest title, body, and Blogger preview")
        if prior:
            return {
                **dict(prior), "duplicate": True,
                "approval_recorded": bool(prior.get("approval_event_id")),
                "public_write_performed": False,
            }
        blockers = _manual_publication_blockers(conn, row, snapshot, request.blog_id)
        if blockers:
            conn.execute(
                "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('publication.manual_request.blocked',%s,%s,%s)",
                (request.blog_id, row["blog_language"], Jsonb({
                    "content_version_id": str(request.content_version_id),
                    "title_sha256": snapshot["title_sha256"],
                    "body_sha256": snapshot["body_sha256"],
                    "html_sha256": snapshot["html_sha256"],
                    "actor_label": request.actor_label,
                    "reasons": blockers,
                    "public_write_performed": False,
                })),
            )
            return {"recorded": False, "state": "publication_blocked", "reasons": blockers,
                    "title_sha256": snapshot["title_sha256"], "body_sha256": snapshot["body_sha256"],
                    "html_sha256": snapshot["html_sha256"], "public_write_performed": False}
        inserted = conn.execute(
            """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
                scheduled_at,status,publication_state,adapter_type,simulation_only,block_reasons,
                oauth_connection_id,live_stage,publication_lane)
            VALUES (%s,%s,%s,%s,now(),'queued','publication_queued','blogger_live',false,'[]',%s,'draft_needed','manual')
            ON CONFLICT(idempotency_key) DO NOTHING
            RETURNING id,status,publication_state,adapter_type,simulation_only""",
            (row["policy_id"], request.blog_id, request.content_version_id,
             request.idempotency_key, row["oauth_connection_id"]),
        ).fetchone()
        if not inserted:
            raise HTTPException(409, "Idempotency key is already bound to another publication request")
        approval = conn.execute(
            """INSERT INTO manual_publication_approval_events
            (job_id,blog_id,content_version_id,import_id,title_sha256,body_sha256,html_sha256,
             actor_label,reason,reviewed_exact_content,assertions_safe_to_publish,
             rights_privacy_harm_checked,idempotency_key)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,true,true,%s)
            RETURNING id,created_at""",
            (inserted["id"], request.blog_id, request.content_version_id,
             snapshot["import_id"], snapshot["title_sha256"], snapshot["body_sha256"],
             snapshot["html_sha256"], request.actor_label, request.reason,
             request.idempotency_key),
        ).fetchone()
        if approval is None:
            raise HTTPException(503, "Manual publication approval event was not persisted")
        review = conn.execute(
            """INSERT INTO post_publication_reviews
            (publishing_job_id,blog_id,content_version_id,import_id,content_id,review_status,review_notes)
            VALUES (%s,%s,%s,%s,%s,'pending','Items below are follow-ups from the user-approved manual publication request; no verification status was changed.')
            ON CONFLICT(publishing_job_id) WHERE publishing_job_id IS NOT NULL
            DO NOTHING RETURNING id""",
            (inserted["id"], request.blog_id, request.content_version_id,
             snapshot["import_id"], snapshot.get("external_content_id")),
        ).fetchone()
        review_id = review["id"] if review else None
        for index, item in enumerate(snapshot["followups"]):
            item_key = "manual-review-" + hashlib.sha256(
                f"{inserted['id']}:{index}:{item['issue_type']}:{item['description']}".encode()
            ).hexdigest()[:48]
            item_row = conn.execute(
                """INSERT INTO post_publication_review_items
                (review_id,issue_type,severity,description,idempotency_key)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                (review_id, item["issue_type"], item["severity"], item["description"], item_key),
            ).fetchone() if review_id else None
            if item_row:
                conn.execute(
                    "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('publication.post_review_item.prepublication_created',%s,%s)",
                    (request.blog_id, Jsonb({"review_id": str(review_id),
                     "item_id": str(item_row["id"]), "job_id": str(inserted["id"]),
                     "issue_type": item["issue_type"], "severity": item["severity"],
                     "source": "manual_publication_assessment"})),
                )
        conn.execute(
            """INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details)
            VALUES (%s,'manual_content_reviewed','publication_queued','exact_user_manual_publish_confirmation',%s)""",
            (inserted["id"], Jsonb({"approval_event_id": approval["id"],
             "title_sha256": snapshot["title_sha256"], "body_sha256": snapshot["body_sha256"],
             "html_sha256": snapshot["html_sha256"], "followup_review_id": str(review_id) if review_id else None})),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('publication.manual_request.approved',%s,%s,%s)",
            (request.blog_id, row["blog_language"], Jsonb({
                "job_id": str(inserted["id"]), "approval_event_id": approval["id"],
                "content_version_id": str(request.content_version_id),
                "import_id": snapshot["import_id"], "generation_method": snapshot["generation_method"],
                "title_sha256": snapshot["title_sha256"], "body_sha256": snapshot["body_sha256"],
                "html_sha256": snapshot["html_sha256"], "actor_label": request.actor_label,
                "reason": request.reason, "reviewed_exact_content": True,
                "assertions_safe_to_publish": True, "rights_privacy_harm_checked": True,
                "followup_review_id": str(review_id) if review_id else None,
                "public_write_performed": False,
            })),
        )
        return {**dict(inserted), "duplicate": False,
                "approval_event_id": approval["id"], "approved_at": approval["created_at"],
                "followup_review_id": str(review_id) if review_id else None,
                "followup_count": len(snapshot["followups"]), "public_write_performed": False}


@router.post("/scheduled-auto/verify-connections")
def verify_scheduled_auto_connections(request: ScheduledConnectionCheckInput) -> dict[str, Any]:
    """Refresh expired tokens through standard OAuth and read-check selected blog identities."""
    from . import blogger_service
    from .google_http import WRITE_SCOPE

    results: list[dict[str, Any]] = []
    with connection() as conn:
        rows = conn.execute(
            """SELECT b.id,b.blog_id,b.url,b.language_code,b.oauth_connection_id,g.status,g.scopes
            FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
            WHERE b.id=ANY(%s::uuid[]) AND b.active ORDER BY b.id""",
            ([str(value) for value in request.blog_ids],),
        ).fetchall()
    if len(rows) != len(set(request.blog_ids)):
        raise HTTPException(404, "One or more selected active blogs were not found")
    for row in rows:
        if row["status"] != "connected" or list(row["scopes"] or []) != [WRITE_SCOPE]:
            results.append({"blog_record_id": str(row["id"]), "blog_id": row["blog_id"],
                            "language_code": row["language_code"], "verified": False,
                            "reason": "connected_blogger_write_scope_required"})
            continue
        try:
            remote = blogger_service.test_connection(UUID(str(row["id"])))
            registered_host = (urlsplit(str(row["url"])).hostname or "").casefold()
            remote_host = (urlsplit(str(remote.get("url") or "")).hostname or "").casefold()
            verified = (str(remote.get("blog_id")) == str(row["blog_id"])
                        and bool(registered_host) and remote_host == registered_host)
            results.append({"blog_record_id": str(row["id"]), "blog_id": str(row["blog_id"]),
                            "url": row["url"], "language_code": row["language_code"],
                            "verified": verified,
                            "remote_blog_id": str(remote.get("blog_id") or ""),
                            "remote_url": remote.get("url"),
                            "last_checked_at": datetime.now(UTC).isoformat()})
        except GoogleFailure as exc:
            results.append({"blog_record_id": str(row["id"]), "blog_id": row["blog_id"],
                            "language_code": row["language_code"], "verified": False,
                            "reason": exc.category, "http_status": exc.status})
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('publication.scheduled_auto.connection_check',%s)",
            (Jsonb({"results": results, "write_scope_required": True,
                    "blogger_write_performed": False, "token_values_logged": False}),),
        )
    return {"results": results, "all_verified": all(item["verified"] for item in results),
            "blogger_write_performed": False}


@router.post("/trends-auto/verify-connections")
def verify_trends_connections(request: ScheduledConnectionCheckInput) -> dict[str, Any]:
    """Reuse only real LIVE receipts tied to the currently mapped OAuth grant."""
    verified = verify_scheduled_auto_connections(request)
    with connection() as conn:
        for result in verified["results"]:
            if not result["verified"]:
                continue
            blog_id = UUID(result["blog_record_id"])
            receipt = conn.execute(
                """SELECT p.id,p.remote_post_id,p.remote_verified_at,j.oauth_connection_id
                FROM publishing_records p JOIN publishing_jobs j ON j.id=p.job_id
                JOIN blogger_blogs b ON b.id=p.blog_id AND b.oauth_connection_id=j.oauth_connection_id
                JOIN blogger_write_operations w ON w.idempotency_key='live:pubjob-'||j.id::text||'-publish'
                WHERE b.id=%s AND p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL
                  AND j.status='succeeded' AND NOT j.simulation_only AND j.adapter_type='blogger_live'
                  AND w.status='succeeded' AND w.operation='publish_draft'
                  AND w.result->>'post_id'=p.remote_post_id AND w.result->>'blog_id'=b.blog_id
                ORDER BY p.remote_verified_at DESC LIMIT 1""", (blog_id,),
            ).fetchone()
            result["write_verified"] = receipt is not None
            if receipt:
                conn.execute("UPDATE blogger_blogs SET test_publish_verified_at=%s WHERE id=%s AND oauth_connection_id=%s AND test_publish_verified_at IS NULL",
                    (receipt["remote_verified_at"], blog_id, receipt["oauth_connection_id"]))
                conn.execute("INSERT INTO audit_events(event_type,blog_id,payload) VALUES (%s,%s,%s)",
                    ("publication.trends_auto.historical_write_verified", blog_id, Jsonb({
                        "publishing_record_id": str(receipt["id"]), "post_id": receipt["remote_post_id"],
                        "historical_verified_at": receipt["remote_verified_at"].isoformat(),
                        "actor": "authenticated_admin", "blogger_write_performed": False})))
    return verified


@router.put("/mode-settings")
def save_mode_settings(request: ModeSettingsInput) -> dict[str, Any]:
    with connection() as conn:
        current = _mode_settings(conn)
        if current["migration_required"]:
            raise HTTPException(409, "Publication settings migration 042 is required")
        # Auto preferences may be recorded for review, but this does not
        # activate the policy or permit Blogger writes. Runtime dispatch has
        # independent activation and live-write gates and remains disabled.
        if request.scope_type == "language":
            found = conn.execute(
                "SELECT 1 FROM languages WHERE code=%s AND active", (request.scope_key,)
            ).fetchone()
            if not found:
                raise HTTPException(404, "Registered language not found")
        if request.scope_type == "blog":
            blog, error = _blog_settings(conn, request.scope_key)
            if error or not blog:
                raise HTTPException(404, "Registered active blog not found")
        if request.configured_mode == "auto":
            active_categories = conn.execute(
                "SELECT slug FROM categories WHERE slug=ANY(%s)",
                (request.allowed_categories,),
            ).fetchall()
            if {row["slug"] for row in active_categories} != set(request.allowed_categories):
                raise HTTPException(422, "Auto categories must match registered category slugs")
        saved = conn.execute(
            """INSERT INTO publication_mode_settings(scope_type,scope_key,configured_mode,
                daily_auto_limit,minimum_interval_minutes,allowed_start_hour,allowed_end_hour,
                timezone,allowed_categories,excluded_topics,max_source_age_hours,retry_limit)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(scope_type,scope_key) DO UPDATE SET
                configured_mode=EXCLUDED.configured_mode,daily_auto_limit=EXCLUDED.daily_auto_limit,
                minimum_interval_minutes=EXCLUDED.minimum_interval_minutes,
                allowed_start_hour=EXCLUDED.allowed_start_hour,allowed_end_hour=EXCLUDED.allowed_end_hour,
                timezone=EXCLUDED.timezone,allowed_categories=EXCLUDED.allowed_categories,
                excluded_topics=EXCLUDED.excluded_topics,max_source_age_hours=EXCLUDED.max_source_age_hours,
                retry_limit=EXCLUDED.retry_limit,updated_at=now()
            RETURNING scope_type,scope_key,configured_mode,daily_auto_limit,minimum_interval_minutes,
                allowed_start_hour,allowed_end_hour,timezone,allowed_categories,excluded_topics,
                max_source_age_hours,retry_limit,emergency_stopped,operations_auto_approved,updated_at""",
            (
                request.scope_type, request.scope_key, request.configured_mode,
                request.daily_auto_limit, request.minimum_interval_minutes,
                request.allowed_start_hour, request.allowed_end_hour, request.timezone,
                request.allowed_categories, request.excluded_topics,
                request.max_source_age_hours, request.retry_limit,
            ),
        ).fetchone()
        assert saved is not None
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('publication.mode.changed',%s)",
            (Jsonb({"scope_type": request.scope_type, "scope_key": request.scope_key,
                "configured_mode": request.configured_mode, "effective_mode": effective_mode(
                    request.configured_mode,
                    emergency_stopped=bool(current["emergency_stopped"]),
                ), "live_auto_enabled": False, "real_writes_enabled": False,
                "daily_auto_limit": request.daily_auto_limit,
                "minimum_interval_minutes": request.minimum_interval_minutes,
                "retry_limit": request.retry_limit}),),
        )
        return {**dict(saved), "live_auto_enabled": False, "real_writes_enabled": False,
                "operations_auto_approved": False}


@router.post("/emergency-stop")
def engage_emergency_stop(request: EmergencyStopInput) -> dict[str, Any]:
    with connection() as conn:
        settings = _mode_settings(conn)
        if settings["migration_required"]:
            raise HTTPException(409, "Publication settings migration 042 is required")
        updated = conn.execute(
            """UPDATE publication_mode_settings SET emergency_stopped=true,updated_at=now()
            WHERE scope_type='global' AND scope_key='' RETURNING emergency_stopped"""
        ).fetchone()
        if not updated:
            raise HTTPException(503, "Global publication settings are unavailable")
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('publication.emergency_stop.engaged',%s)",
            (Jsonb({"emergency_stopped": True, "live_auto_enabled": False,
                    "real_writes_enabled": False}),),
        )
        return {"emergency_stopped": True, "live_auto_enabled": False,
                "real_writes_enabled": False}


class PublicationError(Exception):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class FakeBloggerPublisher:
    """Network-free adapter. Its fake identifiers can never be Blogger IDs."""

    def publish(self, scenario: str) -> dict[str, Any]:
        outcomes = {
            "success": "succeeded",
            "timeout": "failed",
            "auth_failure": "failed",
            "server_failure": "failed",
            "uncertain": "uncertain",
        }
        if scenario not in outcomes:
            raise PublicationError("invalid_mock_scenario")
        return {
            "adapter_type": "fake",
            "simulation_only": True,
            "outcome": outcomes[scenario],
            "scenario": scenario,
            "fake_post_id": f"fake-post-{uuid4()}" if scenario == "success" else None,
            "external_network_calls": 0,
            "real_blog_mutated": False,
        }


class DisabledRealBloggerPublisher:
    """Permanent fail-closed placeholder; deliberately exposes no HTTP client."""

    def publish(self, *_: Any, **__: Any) -> None:
        raise PublicationError("production_writes_disabled")


def transitions_allowed() -> dict[str, tuple[str, ...]]:
    return {
        "draft": ("quality_held", "machine_checked", "publication_blocked"),
        "quality_held": ("machine_checked", "publication_blocked", "cancelled"),
        "machine_checked": ("human_review_pending", "publication_blocked", "cancelled"),
        "human_review_pending": ("human_review_approved", "human_review_rejected", "cancelled"),
        "human_review_rejected": ("human_review_pending", "publication_blocked", "cancelled"),
        "human_review_approved": ("publication_queued", "publication_blocked", "cancelled"),
        "publication_blocked": ("human_review_pending", "cancelled"),
        "publication_queued": ("publishing", "cancelled", "publication_blocked"),
        "publishing": ("published", "publication_failed", "publication_blocked"),
        "publication_failed": ("publication_queued", "publication_blocked", "cancelled"),
        "published": (),
        "cancelled": (),
    }


def transition_allowed(current: str, target: str) -> bool:
    return target in transitions_allowed().get(current, ())


def _assess(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {"state": "draft", "reasons": ["content_or_blog_not_found"]}
    reasons: list[str] = []
    if not row["language_active"]:
        reasons.append("language_inactive")
    if not row["blog_active"]:
        reasons.append("blog_inactive")
    if row["version_language"] != row["blog_language"]:
        reasons.append("blog_language_mismatch")
    if not row["blog_id_value"] or not row["connection_verified_at"]:
        reasons.append("blog_connection_unverified")
    if row["oauth_status"] != "connected":
        reasons.append("oauth_connection_unavailable")
    if row["test_publish_verified_at"] is None:
        reasons.append("test_publish_not_verified")
    if not row["policy_id"]:
        reasons.append("publication_policy_missing")
    elif not row["policy_active"]:
        reasons.append("publication_policy_inactive")
    if row["auto_publish_allowed"]:
        reasons.append("unexpected_auto_publish_enabled")
    if not row["machine_passed"]:
        reasons.append("machine_quality_not_passed")
    if not row.get("sources_reviewed", False):
        reasons.append("reviewed_source_missing")
    if not row.get("evidence_facts_reviewed", False):
        reasons.append("evidence_fact_verification_missing")
    if not row.get("research_package_reviewed", False):
        reasons.append("research_package_not_reviewed")
    if not row.get("rights_reviewed", False):
        reasons.append("source_rights_review_missing")
    if not row.get("seo_passed", False):
        reasons.append("seo_check_not_passed")
    if not row.get("html_ready", False):
        reasons.append("sanitized_blogger_html_missing")
    if row["human_review_required"] or not row["human_review_approved"]:
        reasons.append("human_review_pending")
    if not row.get("publication_approval_approved", False):
        reasons.append("publication_approval_missing_or_stale")
    if not external_policy._blogger_operation_is_approved("blogger_public_publish"):
        reasons.append("production_writes_disabled")
    if not row["publish_ready"]:
        reasons.append("publish_ready_disabled")
    if "machine_quality_not_passed" in reasons:
        state = "quality_held"
    elif "human_review_pending" in reasons:
        state = "human_review_pending"
    else:
        state = "publication_blocked"
    return {"state": state, "reasons": reasons}


def _body_digest(value: str | bytes) -> str:
    body = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _has_identical_body(candidate: str | bytes, existing: list[str | bytes]) -> bool:
    candidate_digest = _body_digest(candidate)
    return any(_body_digest(body) == candidate_digest for body in existing)


def _candidate(conn: Any, version_id: UUID, blog_id: UUID) -> dict[str, Any] | None:
    return cast(
        dict[str, Any] | None,
        conn.execute(
            """SELECT v.id AS content_version_id,v.group_id,v.version,v.source_version_id,v.title,v.body,v.localization_id,
            l.language_code AS version_language,l.target_country,b.id AS blog_uuid,
            b.language_code AS blog_language,b.url,b.active AS blog_active,
            b.blog_id AS blog_id_value,b.oauth_connection_id,b.connection_verified_at,b.test_publish_verified_at,
            lang.active AS language_active,g.status AS oauth_status,g.scopes AS oauth_scopes,
            p.id AS policy_id,p.active AS policy_active,p.auto_publish_allowed,
            COALESCE(q.machine_passed,false) AS machine_passed,
            COALESCE(q.human_review_required,true) AS human_review_required,
            COALESCE(review.disposition='approved',false) AS human_review_approved,
            COALESCE(approval.action='approved' AND
              (editorial.id IS NULL OR approval.body_sha256=editorial.body_sha256),false)
              AS publication_approval_approved,
            COALESCE(q.publish_ready,false) AS publish_ready,
            q.id AS quality_evaluation_id,q.id AS evaluation_id,q.status AS quality_status,
            editorial.id AS editorial_version_id,editorial.html_body,
            editorial.title AS editorial_title,editorial.body AS editorial_body,
            editorial.seo_description,editorial.blogger_labels AS editorial_blogger_labels,
            (SELECT imported.event_group_id FROM external_content_import_content_links link
              JOIN external_content_imports imported ON imported.id=link.import_id
              WHERE link.content_version_id=v.id
              ORDER BY imported.received_at DESC,imported.id DESC LIMIT 1) AS event_group_id,
            (cardinality(COALESCE(q.source_ids,'{}'::uuid[]))>0 AND NOT EXISTS (
              SELECT 1 FROM unnest(q.source_ids) sid
              WHERE NOT EXISTS (SELECT 1 FROM research_sources s
                JOIN LATERAL (SELECT approved FROM source_reviews WHERE source_id=s.id
                  ORDER BY review_sequence DESC LIMIT 1) review ON review.approved
                WHERE s.id=sid AND s.valid_until>now()
                  AND NOT EXISTS (SELECT 1 FROM research_sources newer
                    WHERE newer.keyword_id=s.keyword_id AND newer.url=s.url AND newer.revision>s.revision))
            )) AS sources_reviewed,
            (cardinality(COALESCE(q.fact_ids,'{}'::uuid[]))>0 AND NOT EXISTS (
              SELECT 1 FROM unnest(q.fact_ids) fid LEFT JOIN evidence_facts fact ON fact.id=fid
              WHERE fact.id IS NULL OR fact.verification_status<>'source_span_verified'
            )) AS evidence_facts_reviewed,
            EXISTS (SELECT 1 FROM external_content_import_content_links link
              JOIN external_content_imports imported ON imported.id=link.import_id
              JOIN LATERAL (SELECT package.status,package.independent_source_count,package.source_ids
                FROM trend_research_packages package WHERE package.id::text=imported.research_package_id
                ORDER BY package.package_version DESC LIMIT 1) package ON true
              WHERE link.content_version_id=v.id
                AND package.status='evidence_ready_for_human_review'
                AND package.independent_source_count>0
                AND package.source_ids && COALESCE(q.source_ids,'{}'::uuid[])) AS research_package_reviewed,
            EXISTS (SELECT 1 FROM external_content_import_content_links link
              JOIN LATERAL (SELECT review_event.rights_reviewed
                FROM external_content_import_review_events review_event
                WHERE review_event.import_id=link.import_id
                  AND review_event.version_id=link.import_version_id
                ORDER BY review_event.created_at DESC,review_event.id DESC LIMIT 1) latest_rights_review ON true
              WHERE link.content_version_id=v.id AND latest_rights_review.rights_reviewed) AS rights_reviewed,
            EXISTS (SELECT 1 FROM seo_audits seo WHERE seo.content_version_id=v.id
              AND seo.passed AND seo.profile_id=(SELECT profile_id FROM language_profiles
                WHERE language_code=l.language_code AND target_country=l.target_country LIMIT 1)) AS seo_passed,
            (editorial.html_body IS NOT NULL AND editorial.html_body_sha256 IS NOT NULL) AS html_ready
        FROM content_versions v
        JOIN content_localizations l ON l.id=v.localization_id
        JOIN blogger_blogs b ON b.id=%s
        LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        JOIN languages lang ON lang.code=l.language_code
        LEFT JOIN LATERAL (
          SELECT id FROM language_profiles
          WHERE language_code=l.language_code AND target_country=l.target_country
          LIMIT 1
        ) lp ON true
        LEFT JOIN publishing_policies p ON p.blog_id=b.id AND p.profile_id=lp.id
        LEFT JOIN LATERAL (
          SELECT id,id AS evaluation_id,machine_passed,human_review_required,publish_ready,status,
            source_ids,fact_ids
          FROM article_quality_evaluations WHERE content_version_id=v.id
          ORDER BY created_at DESC,id DESC LIMIT 1
        ) q ON true
        LEFT JOIN LATERAL (
          SELECT id,body_sha256,html_body,html_body_sha256,title,body,seo_description,blogger_labels FROM article_editorial_versions
          WHERE evaluation_id=q.evaluation_id AND base_content_version_id=v.id
          ORDER BY revision_number DESC,created_at DESC,id DESC LIMIT 1
        ) editorial ON true
        LEFT JOIN LATERAL (
          SELECT disposition FROM article_human_reviews
          WHERE evaluation_id=q.evaluation_id AND content_version_id=v.id
            AND editorial_version_id IS NOT DISTINCT FROM editorial.id
          ORDER BY created_at DESC,id DESC LIMIT 1
        ) review ON true
        LEFT JOIN LATERAL (
          SELECT action,body_sha256 FROM publication_approval_events
          WHERE evaluation_id=q.evaluation_id AND content_version_id=v.id
            AND editorial_version_id IS NOT DISTINCT FROM editorial.id
          ORDER BY created_at DESC,id DESC LIMIT 1
        ) approval ON true
        WHERE v.id=%s""",
            (blog_id, version_id),
        ).fetchone(),
    )


def _manual_publication_snapshot(conn: Any, row: dict[str, Any] | None) -> dict[str, Any]:
    """Build the exact sanitized manual payload and post-publication follow-ups."""
    from .editorial_html import markdown_to_blogger_html, sanitize_editorial_html

    if row is None:
        return {"blockers": ["content_or_blog_not_found"], "followups": []}
    content_version_id = str(row["content_version_id"])
    imported = conn.execute(
        """SELECT i.id AS import_id,i.external_content_id,i.generation_method,i.language_code,
            v.id AS import_version_id,v.version_number,v.title AS import_title,
            v.body_markdown,v.blogger_labels,v.content_sha256,
            (SELECT id FROM external_content_import_versions newest
              WHERE newest.import_id=i.id ORDER BY newest.version_number DESC LIMIT 1) AS latest_import_version_id
        FROM external_content_import_content_links link
        JOIN external_content_imports i ON i.id=link.import_id
        JOIN external_content_import_versions v ON v.id=link.import_version_id
        WHERE link.content_version_id=%s
        ORDER BY v.version_number DESC,i.received_at DESC,i.id DESC LIMIT 1""",
        (content_version_id,),
    ).fetchone()
    blockers: list[str] = []
    if not imported:
        blockers.append("content_import_link_required")
    elif str(imported["latest_import_version_id"]) != str(imported["import_version_id"]):
        blockers.append("stale_import_version")
    title = str(row.get("editorial_title") or row.get("title") or "").strip()
    body = str(row.get("editorial_body") or row.get("body") or "")
    if not title:
        blockers.append("publication_title_missing")
    if not body.strip():
        blockers.append("publication_body_missing")
    raw_html = str(row.get("html_body") or "")
    labels = list(row.get("editorial_blogger_labels") or [])
    if not labels and imported:
        labels = list(imported.get("blogger_labels") or [])
    if not raw_html and imported:
        assessment = conn.execute(
            """SELECT safe_html FROM external_content_import_assessments
            WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1""",
            (imported["import_id"], imported["import_version_id"]),
        ).fetchone()
        raw_html = str(assessment.get("safe_html") or "") if assessment else ""
    try:
        if not raw_html:
            raw_html = markdown_to_blogger_html(body, post_title=title)
        safe_html, _plain_text = sanitize_editorial_html(raw_html, post_title=title)
    except (ValueError, TypeError):
        safe_html = ""
        blockers.append("sanitized_blogger_html_unavailable")
    if not safe_html:
        blockers.append("sanitized_blogger_html_unavailable")
    if len(labels) > 10 or any(not str(label).strip() or len(str(label)) > 100 for label in labels):
        blockers.append("blogger_labels_invalid")

    followups: list[dict[str, str]] = []
    def followup(issue_type: str, severity: str, description: str) -> None:
        followups.append({"issue_type": issue_type, "severity": severity, "description": description})

    if not row.get("machine_passed"):
        followup("other", "medium", "기계 품질 검사 미통과 항목을 게시 후 확인하세요.")
    if not row.get("sources_reviewed"):
        followup("source", "medium", "출처 원문과 이용 조건을 추가 확인하세요.")
    if not row.get("evidence_facts_reviewed"):
        followup("number", "medium", "주요 주장과 수치의 근거를 보강하세요.")
    if not row.get("rights_reviewed"):
        followup("copyright", "medium", "출처의 이용 조건과 인용 범위를 확인하세요.")
    if not row.get("seo_passed"):
        followup("other", "low", "SEO 제목·설명과 검색 의도를 보완하세요.")
    if row.get("human_review_required") or not row.get("human_review_approved"):
        followup("other", "low", "편집 검토 기록이 완료되지 않았습니다.")
    if not row.get("publish_ready"):
        followup("other", "low", "일반 publish_ready 평가 미통과 상태를 게시 후 검토하세요.")

    return {
        "blockers": list(dict.fromkeys(blockers)), "followups": followups,
        "title": title, "body": body, "safe_html": safe_html, "blogger_labels": labels,
        "title_sha256": _body_digest(title), "body_sha256": _body_digest(body),
        "html_sha256": _body_digest(safe_html),
        "import_id": str(imported["import_id"]) if imported else None,
        "import_version_id": str(imported["import_version_id"]) if imported else None,
        "external_content_id": imported.get("external_content_id") if imported else None,
        "generation_method": imported.get("generation_method") if imported else None,
    }


def _manual_publication_blockers(
    conn: Any, row: dict[str, Any] | None, snapshot: dict[str, Any], blog_id: UUID,
    *, ignore_job_id: UUID | None = None,
) -> list[str]:
    """Hard safety and operational checks; quality gaps remain follow-ups."""
    if row is None:
        return ["content_or_blog_not_found"]
    reasons = list(snapshot.get("blockers") or [])
    if not row.get("language_active"):
        reasons.append("language_inactive")
    if not row.get("blog_active"):
        reasons.append("blog_inactive")
    if row.get("version_language") != row.get("blog_language"):
        reasons.append("blog_language_mismatch")
    if not row.get("blog_id_value") or not row.get("connection_verified_at"):
        reasons.append("blog_connection_unverified")
    from .google_http import WRITE_SCOPE
    if row.get("oauth_status") != "connected" or list(row.get("oauth_scopes") or []) != [WRITE_SCOPE]:
        reasons.append("blogger_write_oauth_not_verified")
    if not row.get("policy_id"):
        reasons.append("publication_policy_missing")
    modes = _mode_settings(conn)
    if modes.get("migration_required"):
        reasons.append("publication_modes_unavailable")
    else:
        blog, error = _blog_settings(conn, str(blog_id))
        if error or not blog:
            reasons.append(error or "registered_blog_unavailable")
        else:
            mode = resolve_mode(modes["settings"], str(blog["language_code"]), str(blog_id))
            if mode["configured_mode"] != "manual":
                reasons.append("target_uses_auto_mode")
        if modes["emergency_stopped"]:
            reasons.append("publication_emergency_stop_active")
    if external_policy._blogger_policy_approval() is None:
        reasons.append("blogger_zero_cost_policy_required")
    try:
        BloggerLivePublisher._target(blog_id)
    except GoogleFailure as exc:
        reasons.append(exc.category)
    newest = conn.execute(
        """SELECT id FROM content_versions WHERE group_id=%s AND localization_id=%s
        ORDER BY version DESC,created_at DESC,id DESC LIMIT 1""",
        (row["group_id"], row["localization_id"]),
    ).fetchone()
    if newest and str(newest["id"]) != str(row["content_version_id"]):
        reasons.append("stale_content_version")
    existing = conn.execute(
        """SELECT id,status,publication_state FROM publishing_jobs
        WHERE blog_id=%s AND content_version_id=%s AND NOT simulation_only
          AND adapter_type='blogger_live' AND publication_lane='manual'
          AND (%s::uuid IS NULL OR id<>%s::uuid)
        ORDER BY updated_at DESC,id DESC LIMIT 1""",
        (blog_id, row["content_version_id"], ignore_job_id, ignore_job_id),
    ).fetchone()
    if existing:
        reasons.append("manual_live_job_already_exists")
    record = conn.execute(
        "SELECT 1 FROM publishing_records WHERE blog_id=%s AND content_version_id=%s LIMIT 1",
        (blog_id, row["content_version_id"]),
    ).fetchone()
    if record:
        reasons.append("remote_publication_already_recorded")
    return list(dict.fromkeys(reasons))


@router.get('/worker-jobs')
def worker_job_monitor(
    view: Literal['all','queued','running','published','draft_saved','failed','pre_job_failure'] = 'all',
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    from .publication_monitor import snapshot
    return snapshot(view,page,page_size)


def publication_list_flow(row: dict[str, Any]) -> str:
    """A Worker wait requires a persisted Job; verified remote state wins."""
    if row.get('remote_post_id') and row.get('remote_verified_at'):
        return 'published'
    if not row.get('active_job_id'):
        return 'review_needed'
    return 'publishing' if row.get('active_job_status') == 'running' else 'queued'


@router.get("")
def list_publications(
    view: Literal["queue", "review", "published", "held", "auto_failure"] = Query("review"),
    q: str = Query("", max_length=200),
    language_code: str = Query("", max_length=35),
    blog_id: str = Query("", max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict[str, Any]:
    with connection() as conn:
        mode_data = _mode_settings(conn)
        raw_latest_count_row = conn.execute(
            """SELECT count(*)::int AS count FROM (
              SELECT DISTINCT ON (v.group_id,v.localization_id,b.id) v.group_id,v.localization_id,b.id
              FROM content_versions v JOIN content_localizations l ON l.id=v.localization_id
              JOIN blogger_blogs b ON b.language_code=l.language_code AND b.active
              ORDER BY v.group_id,v.localization_id,b.id,v.version DESC,v.created_at DESC,v.id DESC
            ) latest"""
        ).fetchone()
        if raw_latest_count_row is None:
            raise HTTPException(503, "Publication list count is unavailable")
        raw_latest_count = raw_latest_count_row["count"]
        rows = conn.execute(
            """WITH latest AS (
              SELECT DISTINCT ON (v.group_id,v.localization_id,b.id)
                v.id AS content_version_id,v.group_id,v.localization_id,v.version,v.title,v.body,v.created_at AS version_created_at,
                l.language_code,l.target_country,b.id AS blog_uuid,b.url,b.display_name AS blog_name,
                b.blog_id AS blogger_blog_id,b.active AS blog_active,b.oauth_connection_id,
                b.connection_verified_at,b.test_publish_verified_at
              FROM content_versions v
              JOIN content_localizations l ON l.id=v.localization_id
              JOIN blogger_blogs b ON b.language_code=l.language_code AND b.active
              ORDER BY v.group_id,v.localization_id,b.id,v.version DESC,v.created_at DESC,v.id DESC
            )
            SELECT latest.*,lang.active AS language_active,g.status AS oauth_status,
              p.id AS policy_id,p.active AS policy_active,p.auto_publish_allowed,
              COALESCE(q.machine_passed,false) AS machine_passed,
              COALESCE(q.human_review_required,true) AS human_review_required,
              COALESCE(q.publish_ready,false) AS publish_ready,q.status AS quality_status,q.id AS evaluation_id,q.model AS model_name,
              imported.import_id,imported.generation_method,imported.google_trends_based,
              imported.research_package_id,imported.event_group_id,
              COALESCE(imported.title,imported.category) AS topic,
              publication.published_at AS remote_published_at,publication.remote_post_id,
              publication.remote_url,publication.remote_verified_at,publication.remote_status,
              active_job.id AS active_job_id,active_job.status AS active_job_status,
              active_job.publication_state AS active_job_publication_state,
              active_job.scheduled_at AS next_publish_at
            FROM latest
            JOIN languages lang ON lang.code=latest.language_code
            LEFT JOIN google_connections g ON g.id=latest.oauth_connection_id
            LEFT JOIN language_profiles lp ON lp.language_code=latest.language_code AND lp.target_country=latest.target_country
            LEFT JOIN publishing_policies p ON p.blog_id=latest.blog_uuid AND p.profile_id=lp.id
            LEFT JOIN LATERAL (SELECT machine_passed,human_review_required,publish_ready,status,id,model
              FROM article_quality_evaluations WHERE content_version_id=latest.content_version_id
              ORDER BY created_at DESC,id DESC LIMIT 1) q ON true
            LEFT JOIN LATERAL (SELECT imported.id AS import_id,imported.generation_method,
                NULL::boolean AS google_trends_based,imported.research_package_id,imported.event_group_id,
                imported.title,imported.category
              FROM external_content_import_content_links link
              JOIN external_content_imports imported ON imported.id=link.import_id
              WHERE link.content_version_id=latest.content_version_id
              ORDER BY imported.received_at DESC,imported.id DESC LIMIT 1) imported ON true
            LEFT JOIN LATERAL (SELECT r.published_at,r.remote_post_id,r.remote_url,r.remote_verified_at,r.remote_status
              FROM publishing_records r JOIN content_versions pv ON pv.id=r.content_version_id
              JOIN content_localizations pl ON pl.id=pv.localization_id
              WHERE r.blog_id=latest.blog_uuid AND pv.group_id=latest.group_id
                AND pl.language_code=latest.language_code AND pl.target_country=latest.target_country
                AND r.remote_status='LIVE' AND r.remote_verified_at IS NOT NULL
              ORDER BY r.published_at DESC,r.id DESC LIMIT 1) publication ON true
            LEFT JOIN LATERAL (SELECT j.id,j.status,j.publication_state,j.scheduled_at
              FROM publishing_jobs j JOIN content_versions jv ON jv.id=j.content_version_id
              JOIN content_localizations jl ON jl.id=jv.localization_id
              WHERE j.blog_id=latest.blog_uuid AND jv.group_id=latest.group_id
                AND jl.language_code=latest.language_code AND jl.target_country=latest.target_country
                AND j.status IN ('queued','running') AND NOT j.simulation_only
              ORDER BY j.scheduled_at,j.id LIMIT 1) active_job ON true
            WHERE trim(lower(latest.title)) NOT IN ('revised','localized','mock','test')
              AND lower(latest.title) NOT LIKE 'mock pipeline verification%'
              AND position('test only' in lower(latest.title))=0
            ORDER BY latest.version_created_at DESC,latest.content_version_id DESC"""
        ).fetchall()
        jobs = conn.execute(
            """SELECT j.id,j.content_version_id,j.blog_id,b.language_code,b.url,v.title AS content_title,
                j.status,j.publication_state,j.scheduled_at,j.schedule_timezone,j.block_reasons,
                j.attempts,j.retry_count,j.last_error_category,j.updated_at,
                j.adapter_type,j.simulation_only,j.live_stage,j.remote_post_id,j.publication_lane,
                imported.import_id,imported.generation_method,
                live_record.remote_url,live_record.remote_status,live_record.remote_verified_at,
                live_record.published_at,
                (SELECT q.id FROM article_quality_evaluations q
                 WHERE q.content_version_id=j.content_version_id
                 ORDER BY q.created_at DESC,q.id DESC LIMIT 1) AS evaluation_id,
                (SELECT count(*) FROM publication_attempts a WHERE a.job_id=j.id) AS simulation_count
                ,(SELECT count(*) FROM live_publication_attempts la WHERE la.job_id=j.id) AS live_attempt_count
            FROM publishing_jobs j JOIN blogger_blogs b ON b.id=j.blog_id
            LEFT JOIN content_versions v ON v.id=j.content_version_id
            LEFT JOIN LATERAL (SELECT i.id AS import_id,i.generation_method
              FROM external_content_import_content_links l JOIN external_content_imports i ON i.id=l.import_id
              WHERE l.content_version_id=j.content_version_id ORDER BY i.received_at DESC,i.id DESC LIMIT 1
            ) imported ON true
            LEFT JOIN LATERAL (SELECT remote_url,remote_status,remote_verified_at,published_at
              FROM publishing_records r WHERE r.job_id=j.id ORDER BY r.published_at DESC LIMIT 1) live_record ON true
             ORDER BY j.scheduled_at DESC,j.id DESC"""
        ).fetchall()
        attempts = conn.execute(
            "SELECT id,job_id,scenario,outcome,fake_post_id,result,created_at FROM publication_attempts ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        live_attempt_relation = conn.execute(
            "SELECT to_regclass('public.live_publication_attempts') AS name"
        ).fetchone()
        live_attempt_relation_name = live_attempt_relation["name"] if live_attempt_relation else None
        live_attempts = conn.execute(
            """SELECT id,job_id,attempt_no,operation,outcome,remote_post_id,http_status,error_category,created_at
              FROM live_publication_attempts ORDER BY created_at DESC LIMIT 100"""
        ).fetchall() if live_attempt_relation_name else []
        worker = conn.execute(
            """SELECT process_id,status,last_error_category,last_seen_at,updated_at
            FROM worker_heartbeats WHERE service_name='publication_worker'"""
        ).fetchone()
        queued = conn.execute(
            """SELECT count(*) AS n FROM publishing_jobs
            WHERE status='queued' AND simulation_only AND adapter_type='fake'"""
        ).fetchone()
        queued_drafts = conn.execute(
            """SELECT count(*) AS n FROM blogger_write_operations
            WHERE operation='create_draft' AND status='pending'
              AND result->>'confirmation_recorded'='true'"""
        ).fetchone()
        assert queued is not None
        assert queued_drafts is not None
        published_total = conn.execute(
            """SELECT count(*)::int AS n FROM publishing_records
              WHERE remote_status='LIVE' AND remote_verified_at IS NOT NULL"""
        ).fetchone()
        if published_total is None:
            raise HTTPException(503, "Published count is unavailable")
        latest_candidates: list[dict[str, Any]] = []
        seen_bodies: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        duplicate_suppressed = 0
        for raw_candidate in rows:
            candidate = dict(raw_candidate)
            if any(marker in str(candidate.get("model_name") or "").casefold() for marker in ("qwen", "llama")):
                continue
            candidate["id"] = str(candidate["content_version_id"])
            candidate["group_id"] = str(candidate["group_id"])
            candidate["content_version_id"] = str(candidate["content_version_id"])
            candidate["blog_id"] = str(candidate["blog_uuid"])
            body = str(candidate.pop("body", ""))
            candidate["body_sha256"] = _body_digest(body)
            body_scope = (candidate["blog_id"], candidate["language_code"])
            scoped_seen = seen_bodies.setdefault(body_scope, [])
            if any(
                (bool(body) and digest == candidate["body_sha256"])
                or same_manuscript_content(candidate["title"], body, prior_title, prior_body)
                for digest, prior_title, prior_body in scoped_seen
            ):
                duplicate_suppressed += 1
                continue
            scoped_seen.append((candidate["body_sha256"], str(candidate["title"]), body))
            candidate["version_language"] = candidate["language_code"]
            candidate["blog_language"] = candidate["language_code"]
            candidate["blog_id_value"] = candidate["blogger_blog_id"]
            candidate["mode_policy"] = resolve_mode(
                mode_data["settings"], str(candidate["language_code"]), str(candidate["blog_id"])
            )
            candidate["effective_mode"] = effective_mode(
                candidate["mode_policy"]["configured_mode"],
                emergency_stopped=bool(mode_data["emergency_stopped"]),
            )
            candidate['has_publishing_job'] = bool(candidate['active_job_id'])
            candidate['publishing_job_id'] = str(candidate['active_job_id']) if candidate['active_job_id'] else None
            candidate['operational_status'] = publication_list_flow(candidate)
            if candidate['operational_status'] in {'published','queued','publishing'}:
                candidate["eligibility_reasons"] = []
            else:
                candidate["operational_status"] = "review_needed"
                candidate["eligibility_reasons"] = (
                    ["quality_evaluation_missing"] if candidate["evaluation_id"] is None
                    else ["quality_not_passed"] if not candidate["machine_passed"]
                    else ["editorial_source_rights_and_publication_review_required"]
                )
            candidate["auto_eligibility"] = {
                "eligible": False, "auto_eligible": False, "dispatchable": False,
                "reasons": ["automatic_publication_policy_inactive"],
                "human_review_required": True, "human_approval_recorded": False,
                "simulation_only": True,
            }
            latest_candidates.append(candidate)

        publication_records = [dict(row) for row in conn.execute(
            """SELECT r.id AS record_id,r.job_id,r.blog_id,b.language_code,b.display_name AS blog_name,
            b.url AS blog_url,b.blog_id AS blogger_blog_id,r.content_version_id,v.group_id,v.title,
            r.remote_post_id,r.remote_url,r.remote_status,r.remote_verified_at,r.published_at,
            imported.import_id,imported.generation_method,imported.google_trends_based,
            evaluation.evaluation_id,evaluation.model
            FROM publishing_records r JOIN blogger_blogs b ON b.id=r.blog_id
            JOIN content_versions v ON v.id=r.content_version_id
            LEFT JOIN LATERAL (SELECT imported.id AS import_id,imported.generation_method,
                NULL::boolean AS google_trends_based FROM external_content_import_content_links link
                JOIN external_content_imports imported ON imported.id=link.import_id
                WHERE link.content_version_id=v.id ORDER BY imported.received_at DESC,imported.id DESC LIMIT 1
            ) imported ON true
            LEFT JOIN LATERAL (SELECT q.id AS evaluation_id,q.model FROM article_quality_evaluations q
                WHERE q.content_version_id=v.id ORDER BY q.created_at DESC,q.id DESC LIMIT 1
            ) evaluation ON true
            WHERE r.remote_status='LIVE' AND r.remote_verified_at IS NOT NULL
            ORDER BY r.published_at DESC,r.id DESC"""
        ).fetchall()]
        held_jobs = [dict(row) for row in jobs if row["status"] in {"blocked", "failed", "uncertain"}
                     or row["publication_state"] in {"quality_held", "publication_blocked", "publication_failed"}]

        queue_items: list[dict[str, Any]] = []
        review_items: list[dict[str, Any]] = []
        for candidate in latest_candidates:
            if candidate["operational_status"] == "published":
                continue
            item = {
                **candidate,
                "item_type": "manuscript",
                "topic": candidate.get("topic") or candidate.get("title"),
                "blog_name": candidate.get("blog_name") or candidate.get("url"),
                "status": candidate["operational_status"],
                "created_at": candidate["version_created_at"],
                "remote_url": None,
            }
            if candidate["operational_status"] in {"queued", "publishing", "queueable"}:
                queue_items.append(item)
            else:
                review_items.append(item)
        published_items = [{
            "item_type": "published", "id": str(row["record_id"]),
            "content_version_id": str(row["content_version_id"]), "group_id": str(row["group_id"]),
            "title": row["title"], "language_code": row["language_code"],
            "blog_id": str(row["blog_id"]), "blog_name": row["blog_name"],
            "url": row["blog_url"], "blogger_blog_id": row["blogger_blog_id"],
            "topic": row["title"], "status": "published", "created_at": row["published_at"],
            "remote_post_id": row["remote_post_id"], "remote_url": row["remote_url"],
            "remote_status": row["remote_status"], "remote_verified_at": row["remote_verified_at"],
            "published_at": row["published_at"], "eligibility_reasons": [],
            "import_id": str(row["import_id"]) if row.get("import_id") else None,
            "generation_method": row.get("generation_method"),
            "evaluation_id": str(row["evaluation_id"]) if row.get("evaluation_id") else None,
            "model_name": row.get("model"),
            "research_package_id": None, "source_names": None,
        } for row in publication_records]
        held_items = [{
            "item_type": "job", "id": str(row["id"]),
            "content_version_id": str(row["content_version_id"]),
            "title": row["content_title"] or "제목 없음", "language_code": row["language_code"],
            "blog_id": str(row["blog_id"]), "blog_name": row["url"], "url": row["url"],
            "blogger_blog_id": None, "topic": row["content_title"],
            "status": row["publication_state"], "created_at": row["updated_at"],
            "next_publish_at": row["scheduled_at"], "remote_post_id": row["remote_post_id"],
            "remote_url": None, "remote_status": None, "remote_verified_at": None,
            "simulation_only": row["simulation_only"], "adapter_type": row["adapter_type"],
            "attempts": row["attempts"], "retry_count": row.get("retry_count") or 0,
            "last_retry_at": row.get("updated_at") if row.get("retry_count") else None,
            "last_error_category": row["last_error_category"],
            "eligibility_reasons": row["block_reasons"] or [],
            "generation_method": row.get("generation_method"),
            "publication_lane": row.get("publication_lane"),
            "google_trends_based": row.get("google_trends_based"),
            "auto_publication_failure": row.get("publication_lane") == "scheduled_auto",
            "failure_stage": "publication_worker" if row.get("last_error_category") else "eligibility",
            "failure_reason_code": row.get("last_error_category") or ((row["block_reasons"] or [None])[0]),
            "manual_publication_available": row.get("import_id") is not None,
            "import_id": str(row["import_id"]) if row.get("import_id") else None,
            "research_package_id": None, "source_names": None,
        } for row in held_jobs]

        # Once a real job exists its current state belongs in the job views;
        # the historical pre-job failure remains in the append-only audit log.
        auto_failure_items: list[dict[str, Any]] = []
        failure_events = conn.execute(
            """WITH latest AS (
              SELECT DISTINCT ON (payload->>'import_id',payload->>'content_version_id',payload->>'blog_record_id')
                id,event_type,payload FROM audit_events
              WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
              ORDER BY payload->>'import_id',payload->>'content_version_id',payload->>'blog_record_id',id DESC
            )
            SELECT e.id,e.event_type,e.payload,i.generation_method,i.language_code,
              v.title,b.id AS blog_record_id,b.display_name AS blog_name,b.url,
              v.id AS content_version_id,
              (SELECT COALESCE(max(j.retry_count),0)::int FROM publishing_jobs j
               WHERE j.content_version_id=v.id AND j.blog_id=b.id) AS retry_count
            FROM latest e JOIN external_content_imports i ON i.id=(e.payload->>'import_id')::uuid
            LEFT JOIN content_versions v ON v.id=NULLIF(e.payload->>'content_version_id','')::uuid
            LEFT JOIN blogger_blogs b ON b.id=NULLIF(e.payload->>'blog_record_id','')::uuid
            WHERE e.event_type='publication.auto_failure.recorded'
              AND NOT EXISTS (SELECT 1 FROM publishing_jobs j
                JOIN external_content_import_content_links l
                  ON l.content_version_id=j.content_version_id AND l.import_id=i.id
                WHERE j.blog_id=b.id AND j.content_version_id=v.id
                  AND j.adapter_type='blogger_live' AND NOT j.simulation_only
                  AND (j.status IN ('queued','running','failed','blocked','uncertain') OR j.publication_state='draft_saved'))
              AND NOT EXISTS (SELECT 1 FROM publishing_records r WHERE r.blog_id=b.id
                AND r.content_version_id=v.id AND r.remote_status='LIVE' AND r.remote_verified_at IS NOT NULL)
            ORDER BY e.id DESC"""
        ).fetchall()
        for row in failure_events:
            failure = dict(row)
            key = (str(failure.get("content_version_id")), str(failure.get("blog_record_id")))
            if any((item.get("content_version_id"), item.get("blog_id")) == key for item in auto_failure_items):
                continue
            payload = failure["payload"]
            auto_failure_items.append({
                "item_type": "auto_failure", "id": str(failure["id"]),
                "content_version_id": str(failure.get("content_version_id") or payload.get("content_version_id") or ""),
                "title": failure.get("title") or "제목 없음", "language_code": failure.get("language_code"),
                "blog_id": str(failure.get("blog_record_id") or payload.get("blog_record_id") or ""),
                "blog_name": failure.get("blog_name") or failure.get("url"), "url": failure.get("url"),
                "topic": failure.get("title"), "status": "auto_publication_failed",
                "created_at": payload.get("occurred_at"), "generation_method": failure.get("generation_method"),
                "auto_publication_failure": True, "failure_stage": payload.get("stage"),
                "failure_reason_code": payload.get("failure_reason_code"),
                "eligibility_reasons": payload.get("reason_codes") or [],
                "attempts": 0, "retry_count": failure.get("retry_count") or 0,
                "manual_publication_available": True,
                "import_id": payload.get("import_id"), "job_id": payload.get("job_id"),
            })

        all_views = {
            "queue": queue_items,
            "review": review_items,
            "published": published_items,
            "held": held_items,
            "auto_failure": auto_failure_items,
        }
        summary = {
            "queue": len(queue_items), "review": len(review_items),
            "published": len(published_items), "held": len(held_items),
            "auto_failure": len(auto_failure_items),
            "latest_manuscripts": len(latest_candidates),
            "duplicate_suppressed": duplicate_suppressed,
            "excluded_non_operational": max(0, int(raw_latest_count) - len(latest_candidates) - duplicate_suppressed),
        }
        selected = all_views[view]
        query = q.strip().casefold()
        if query:
            selected = [item for item in selected if query in " ".join(str(item.get(key) or "") for key in (
                "title", "topic", "source_names", "remote_post_id", "content_version_id", "id"
            )).casefold()]
        if language_code:
            selected = [item for item in selected if item.get("language_code") == language_code]
        if blog_id:
            selected = [item for item in selected if item.get("blog_id") == blog_id]
        total_count = len(selected)
        page_count = (total_count + page_size - 1) // page_size
        start = (page - 1) * page_size
        items = selected[start:start + page_size]
        return {
            "candidates": [dict(row) for row in latest_candidates],
            "items": [dict(row) for row in items],
            "view": view,
            "summary": summary,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "jobs": [dict(row) for row in jobs],
            "simulations": [dict(row) for row in attempts],
            "live_attempts": [dict(row) for row in live_attempts],
            "worker": dict(worker) if worker else None,
            "queued_mock_jobs": queued["n"],
            "queued_confirmed_private_drafts": queued_drafts["n"],
            "actual_published_count": int(published_total["n"]),
            "real_writes_enabled": bool(mode_data.get("real_writes_enabled")),
            "publish_ready_enabled": False,
            "adapter_available": "fake_and_guarded_blogger_live_queue",
            "mode_policy": mode_data,
            "operational_limits": {
                "timezone": "Asia/Seoul",
                "global_daily": GLOBAL_DAILY_PUBLISH_LIMIT,
                "language_daily": {**LANGUAGE_DAILY_LIMITS, "en": None},
                "language_hourly": LANGUAGE_HOURLY_LIMITS,
                "english_daily_policy": "remaining_global_capacity",
                "blog_minimum_interval_minutes": 5,
                "account_minimum_interval_minutes": 2,
            },
            "auto_candidate_count": sum(
                1 for candidate in latest_candidates if candidate["auto_eligibility"]["eligible"]
            ),
            "auto_runtime_status": (
                "scoped_scheduled_auto_enabled"
                if (mode_data.get("scoped_write_capability") or {}).get("scheduled_auto")
                else "disabled_or_worker_unavailable"
            ),
            "auto_policy_active": bool((mode_data.get("scheduled_auto_policy") or {}).get("enabled")),
        }


@router.post("/jobs/{job_id}/sync-draft")
def sync_trends_draft(job_id: UUID) -> dict[str, Any]:
    from . import blogger_service
    with connection() as conn:
        row = conn.execute("""SELECT j.blog_id,b.blog_id blogger_id,j.remote_post_id
            FROM publishing_jobs j JOIN blogger_blogs b ON b.id=j.blog_id
            AND b.oauth_connection_id=j.oauth_connection_id
            WHERE j.id=%s AND j.publication_lane='trends_auto' AND j.publication_mode='draft'
              AND j.remote_post_id IS NOT NULL""",(job_id,)).fetchone()
    if not row:
        raise HTTPException(404,"Recorded Trends draft not found")
    remote = blogger_service.post(row["blog_id"],row["remote_post_id"])
    if (str(remote.get("id")) != row["remote_post_id"] or str((remote.get("blog") or {}).get("id")) != row["blogger_id"]
            or remote.get("status") not in {"DRAFT","LIVE"}):
        raise HTTPException(409,"Remote draft identity or status mismatch")
    result = {"job_id":str(job_id),"post_id":row["remote_post_id"],"remote_status":remote["status"],
              "remote_url":remote.get("url") if remote["status"] == "LIVE" else None,"blogger_write_performed":False}
    with connection() as conn:
        conn.execute("INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('publication.trends_draft.synced',%s,%s)",
            (row["blog_id"],Jsonb(result)))
    return result


@router.patch("/jobs/{job_id}/draft-review")
def review_trends_draft(job_id: UUID, request: PostPublicationReviewUpdate) -> dict[str, Any]:
    with connection() as conn:
        if not conn.execute("SELECT 1 FROM blogger_draft_receipts WHERE job_id=%s",(job_id,)).fetchone():
            raise HTTPException(404,"Verified draft receipt not found")
        payload={"job_id":str(job_id),"review_status":request.review_status,"review_notes":request.review_notes,
                 "actor":"authenticated_dashboard_operator","remote_edit_verified":False}
        conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('publication.trends_draft.reviewed',%s)",(Jsonb(payload),))
    return payload


@router.get("/post-publication-reviews")
def list_post_publication_reviews(
    status: Literal["all", "pending", "completed"] = Query("all"),
) -> dict[str, Any]:
    """List manually and automatically published posts whose LIVE status was remotely verified."""
    with connection() as conn:
        rows = conn.execute(
            """SELECT 'publish'::text publication_mode,r.id,r.review_status,r.review_notes,r.created_at,r.updated_at,
                p.remote_url,p.remote_post_id,p.published_at,p.remote_verified_at,
                p.content_version_id,r.content_id,v.title,b.language_code,b.url AS blog_url,
                i.import_id,i.claims AS claim_verification,COALESCE(open_items.n,0)::int AS open_item_count,
                COALESCE(open_items.high_count,0)::int AS high_count,
                COALESCE(items.all_items,'[]'::jsonb) AS review_items
            FROM post_publication_reviews r
            JOIN publishing_records p ON p.id=r.publishing_record_id
            JOIN publishing_jobs j ON j.id=p.job_id
            JOIN content_versions v ON v.id=p.content_version_id
            JOIN blogger_blogs b ON b.id=p.blog_id
            LEFT JOIN LATERAL (SELECT link.import_id,imp.claims FROM external_content_import_content_links link
                JOIN external_content_imports imp ON imp.id=link.import_id
                WHERE link.content_version_id=p.content_version_id ORDER BY link.created_at DESC LIMIT 1) i ON true
            LEFT JOIN LATERAL (SELECT count(*) FILTER(WHERE NOT resolved) AS n,
                count(*) FILTER(WHERE NOT resolved AND severity='high') AS high_count
                FROM post_publication_review_items x WHERE x.review_id=r.id) open_items ON true
            LEFT JOIN LATERAL (SELECT jsonb_agg(jsonb_build_object('id',x.id,'issue_type',x.issue_type,
                'severity',x.severity,'description',x.description,'resolved',x.resolved,
                'resolved_at',x.resolved_at,'created_at',x.created_at) ORDER BY
                CASE x.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,x.created_at DESC) AS all_items
                FROM post_publication_review_items x WHERE x.review_id=r.id) items ON true
            WHERE p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL
              AND (%s='all' OR (%s='pending' AND r.review_status<>'completed')
                OR (%s='completed' AND r.review_status='completed'))
            ORDER BY high_count DESC,open_items.n DESC,p.published_at DESC,r.id""",
            (status,status,status),
        ).fetchall()
        drafts = conn.execute("""SELECT d.job_id id,'draft'::text publication_mode,
            COALESCE(review.payload->>'review_status','pending') review_status,
            COALESCE(review.payload->>'review_notes','') review_notes,d.verified_at published_at,
            d.remote_post_id,COALESCE(sync.payload->>'remote_status','DRAFT') remote_status,
            sync.payload->>'remote_url' remote_url,d.content_version_id,v.title,b.language_code,b.url blog_url,
            0 open_item_count,0 high_count,'[]'::jsonb review_items,i.claims claim_verification
            FROM blogger_draft_receipts d JOIN content_versions v ON v.id=d.content_version_id
            JOIN blogger_blogs b ON b.id=d.blog_id
            LEFT JOIN external_content_import_content_links l ON l.content_version_id=d.content_version_id
            LEFT JOIN external_content_imports i ON i.id=l.import_id
            LEFT JOIN LATERAL (SELECT payload FROM audit_events WHERE event_type='publication.trends_draft.reviewed'
              AND payload->>'job_id'=d.job_id::text ORDER BY id DESC LIMIT 1) review ON true
            LEFT JOIN LATERAL (SELECT payload FROM audit_events WHERE event_type='publication.trends_draft.synced'
              AND payload->>'job_id'=d.job_id::text ORDER BY id DESC LIMIT 1) sync ON true
            WHERE (%s='all' OR (%s='pending' AND COALESCE(review.payload->>'review_status','pending')<>'completed')
              OR (%s='completed' AND review.payload->>'review_status'='completed'))
            ORDER BY d.verified_at DESC""",(status,status,status)).fetchall()
        items = [dict(row) for row in [*rows,*drafts]]
        return {"items":items,"total":len(items),"verified_live_only":False,"verified_remote_only":True}


@router.patch("/post-publication-reviews/{review_id}")
def update_post_publication_review(review_id: UUID, request: PostPublicationReviewUpdate) -> dict[str, Any]:
    with connection() as conn:
        previous = conn.execute(
            "SELECT review_status,review_notes FROM post_publication_reviews WHERE id=%s FOR UPDATE",
            (review_id,),
        ).fetchone()
        if not previous:
            raise HTTPException(404, "Verified scheduled publication review not found")
        open_items = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM post_publication_review_items WHERE review_id=%s AND NOT resolved) AS open",
            (review_id,),
        ).fetchone()
        if request.review_status == "completed" and open_items is not None and open_items["open"]:
            raise HTTPException(409, "Resolve all open follow-up items before completing the review")
        row = conn.execute(
            """UPDATE post_publication_reviews r SET review_status=%s,review_notes=%s,updated_at=now()
            FROM publishing_records p JOIN publishing_jobs j ON j.id=p.job_id
            WHERE r.id=%s AND p.id=r.publishing_record_id AND p.remote_status='LIVE'
              AND p.remote_verified_at IS NOT NULL AND j.publication_lane IN ('scheduled_auto','manual','trends_auto')
            RETURNING r.id,r.review_status,r.review_notes,r.updated_at""",
            (request.review_status, request.review_notes, review_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Verified scheduled publication review not found")
        conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            ("publication.post_review.updated", Jsonb({"review_id": str(review_id),
             "previous_status": previous["review_status"], "review_status": row["review_status"],
             "remote_edit_verified": False,
             "review_notes": row["review_notes"], "actor": "authenticated_dashboard_operator"})))
        return dict(row)


@router.post("/post-publication-reviews/{review_id}/items", status_code=201)
def add_post_publication_review_item(
    review_id: UUID, request: PostPublicationReviewItemInput,
) -> dict[str, Any]:
    with connection() as conn:
        verified = conn.execute(
            """SELECT 1 FROM post_publication_reviews r
            JOIN publishing_records p ON p.id=r.publishing_record_id
            JOIN publishing_jobs j ON j.id=p.job_id
            WHERE r.id=%s AND p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL
              AND j.publication_lane IN ('scheduled_auto','manual','trends_auto') FOR UPDATE OF r""", (review_id,),
        ).fetchone()
        if not verified:
            raise HTTPException(404, "Verified scheduled publication review not found")
        row = conn.execute(
            """INSERT INTO post_publication_review_items(review_id,issue_type,severity,description,idempotency_key)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING
            RETURNING id,review_id,issue_type,severity,description,resolved,resolved_at,created_at""",
            (review_id, request.issue_type, request.severity, request.description, request.idempotency_key),
        ).fetchone()
        if row:
            reopened = conn.execute(
                """UPDATE post_publication_reviews SET review_status='in_progress',updated_at=now()
                WHERE id=%s AND review_status='completed' RETURNING id""", (review_id,),
            ).fetchone()
            conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                ("publication.post_review_item.created", Jsonb({"review_id": str(review_id),
                 "item_id": str(row["id"]), "issue_type": row["issue_type"],
                 "severity": row["severity"], "description": row["description"],
                 "actor": "authenticated_dashboard_operator"})))
            if reopened:
                conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                    ("publication.post_review.reopened", Jsonb({"review_id": str(review_id),
                     "reason": "new_follow_up_item_added", "actor": "authenticated_dashboard_operator"})))
        else:
            row = conn.execute("""SELECT id,review_id,issue_type,severity,description,resolved,resolved_at,created_at
                FROM post_publication_review_items WHERE idempotency_key=%s""", (request.idempotency_key,)).fetchone()
            if row is None:
                raise HTTPException(503, "Publication review item could not be loaded")
            if str(row["review_id"]) != str(review_id):
                raise HTTPException(409, "Idempotency key belongs to a different review")
        return dict(row)


@router.post("/post-publication-reviews/{review_id}/items/{item_id}/resolve")
def resolve_post_publication_review_item(review_id: UUID, item_id: UUID) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """UPDATE post_publication_review_items x SET resolved=true,resolved_at=now(),updated_at=now()
            FROM post_publication_reviews r JOIN publishing_records p ON p.id=r.publishing_record_id
            JOIN publishing_jobs j ON j.id=p.job_id
            WHERE x.id=%s AND x.review_id=r.id AND r.id=%s AND NOT x.resolved
              AND p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL
              AND j.publication_lane IN ('scheduled_auto','manual','trends_auto')
            RETURNING x.id,x.review_id,x.issue_type,x.severity,x.description,x.resolved,x.resolved_at,x.updated_at""",
            (item_id, review_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Open review item not found")
        conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            ("publication.post_review_item.resolved", Jsonb({"review_id": str(review_id),
             "item_id": str(item_id), "issue_type": row["issue_type"],
             "actor": "authenticated_dashboard_operator"})))
        return dict(row)


@router.post("/requests", status_code=201)
def create_request(request: RequestInput) -> dict[str, Any]:
    with connection() as conn:
        row = _candidate(conn, request.content_version_id, request.blog_id)
        if row is None:
            raise HTTPException(404, "Content version or registered blog not found")
        row = dict(row)
        modes = _mode_settings(conn)
        if modes["migration_required"]:
            raise HTTPException(409, "Publication settings migration 042 is required")
        blog, error = _blog_settings(conn, str(request.blog_id))
        if error or not blog:
            raise HTTPException(404, "Registered active blog not found")
        selected_mode = resolve_mode(modes["settings"], str(blog["language_code"]), str(request.blog_id))
        if selected_mode["configured_mode"] != "manual":
            raise HTTPException(409, "Manual request endpoint is unavailable for Auto-configured targets")
        assessed = _assess(row)
        if row["policy_id"] is None:
            conn.execute(
                "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('publication.request.blocked',%s,%s)",
                (
                    request.blog_id,
                    Jsonb(
                        {
                            "content_version_id": str(request.content_version_id),
                            "reasons": assessed["reasons"],
                        }
                    ),
                ),
            )
            return {
                "recorded": False,
                "state": assessed["state"],
                "reasons": assessed["reasons"],
                "real_writes_enabled": False,
            }
        inserted = conn.execute(
            """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
                scheduled_at,status,publication_state,adapter_type,simulation_only,block_reasons)
            VALUES (%s,%s,%s,%s,now(),'blocked',%s,'fake',true,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id,status,publication_state,block_reasons""",
            (
                row["policy_id"],
                request.blog_id,
                request.content_version_id,
                request.idempotency_key,
                assessed["state"],
                Jsonb(assessed["reasons"]),
            ),
        ).fetchone()
        if inserted is None:
            existing = conn.execute(
                "SELECT id,blog_id,content_version_id,status,publication_state,block_reasons FROM publishing_jobs WHERE idempotency_key=%s",
                (request.idempotency_key,),
            ).fetchone()
            if (
                existing is None
                or str(existing["blog_id"]) != str(request.blog_id)
                or str(existing["content_version_id"]) != str(request.content_version_id)
            ):
                raise HTTPException(409, "Idempotency key conflict")
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('publication.request.duplicate_blocked',%s)",
                (Jsonb({"job_id": str(existing["id"]), "simulation_only": True}),),
            )
            return {**dict(existing), "duplicate": True, "real_writes_enabled": False}
        event = conn.execute(
            """INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details)
                VALUES (%s,NULL,%s,'eligibility_gate_failed',%s) RETURNING id""",
            (
                inserted["id"],
                assessed["state"],
                Jsonb(
                    {
                        "reasons": assessed["reasons"],
                        "machine_passed": row["machine_passed"],
                        "human_review_required": row["human_review_required"],
                        "simulation_only": True,
                    }
                ),
            ),
        ).fetchone()
        assert event is not None and inserted is not None
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,payload) VALUES ('publication.request.blocked',%s,%s)",
            (
                request.blog_id,
                Jsonb(
                    {
                        "job_id": str(inserted["id"]),
                        "event_id": event["id"],
                        "reasons": assessed["reasons"],
                        "simulation_only": True,
                    }
                ),
            ),
        )
        return {**dict(inserted), "duplicate": False, "real_writes_enabled": False}


@router.post("/live-requests", status_code=201)
def create_live_request(request: RequestInput) -> dict[str, Any]:
    """Queue a real Blogger workflow only after exact content and operations gates pass."""
    with connection() as conn:
        migration = conn.execute(
            "SELECT to_regclass('public.live_publication_attempts') AS ready"
        ).fetchone()
        if migration is None or not migration["ready"]:
            raise HTTPException(503, "Blogger live publication migration 049 is required")
        existing = conn.execute(
            "SELECT id,blog_id,content_version_id,status,publication_state,adapter_type,simulation_only FROM publishing_jobs WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone()
        if existing:
            if (str(existing["blog_id"]) != str(request.blog_id)
                    or str(existing["content_version_id"]) != str(request.content_version_id)):
                raise HTTPException(409, "Idempotency key conflict")
            if existing["adapter_type"] != "blogger_live" or existing["simulation_only"]:
                raise HTTPException(409, "Idempotency key belongs to a mock publication job")
            return {**dict(existing), "duplicate": True, "adapter_type": "blogger_live",
                    "simulation_only": False, "real_writes_enabled": False}
        row = _candidate(conn, request.content_version_id, request.blog_id)
        if row is None:
            raise HTTPException(404, "Content version or registered blog not found")
        row = dict(row)
        reasons = list(_assess(row)["reasons"])
        newest = conn.execute(
            """SELECT id FROM content_versions WHERE group_id=%s AND localization_id=%s
            ORDER BY version DESC,created_at DESC,id DESC LIMIT 1""",
            (row["group_id"], row["localization_id"]),
        ).fetchone()
        if newest and str(newest["id"]) != str(request.content_version_id):
            reasons.append("stale_content_version")
        if row.get("event_group_id"):
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"publication:{request.blog_id}:{row['event_group_id']}:{_body_digest(str(row['body']))}",),
            )
            duplicate_bodies = conn.execute(
                """SELECT v.body FROM publishing_jobs j
                JOIN content_versions v ON v.id=j.content_version_id
                WHERE j.blog_id=%s AND j.content_version_id<>%s
                  AND (j.status IN ('queued','running','uncertain','succeeded','published') OR EXISTS (
                    SELECT 1 FROM publishing_records r WHERE r.job_id=j.id
                      AND r.remote_status='LIVE' AND r.remote_verified_at IS NOT NULL))
                  AND EXISTS (SELECT 1 FROM external_content_import_content_links link
                    JOIN external_content_imports imported ON imported.id=link.import_id
                    WHERE link.content_version_id=v.id AND imported.event_group_id=%s)""",
                (request.blog_id, request.content_version_id, row["event_group_id"]),
            ).fetchall()
            if _has_identical_body(str(row["body"]), [str(existing["body"]) for existing in duplicate_bodies]):
                reasons.append("same_event_same_blog_identical_body_already_queued_or_published")
        modes = _mode_settings(conn)
        if modes["migration_required"]:
            reasons.append("publication_modes_unavailable")
        else:
            blog, error = _blog_settings(conn, str(request.blog_id))
            if error or not blog:
                reasons.append(error or "registered_blog_unavailable")
            else:
                selected = resolve_mode(modes["settings"], str(blog["language_code"]), str(request.blog_id))
                if selected["configured_mode"] != "manual":
                    reasons.append("auto_publication_requires_separate_operations_approval")
            if modes["emergency_stopped"]:
                reasons.append("global_emergency_stop_active")
        if not external_policy._blogger_operation_is_approved("blogger_public_publish"):
            reasons.append("separate_public_publish_operations_approval_required")
        try:
            target = BloggerLivePublisher._target(request.blog_id)
        except GoogleFailure as exc:
            reasons.append(exc.category)
            target = None
        if reasons or target is None:
            conn.execute(
                "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('publication.live_request.blocked',%s,%s,%s)",
                (request.blog_id, row["blog_language"], Jsonb({
                    "content_version_id": str(request.content_version_id),
                    "reasons": sorted(set(reasons)), "live_write_performed": False,
                    "publish_ready": bool(row["publish_ready"]),
                })),
            )
            return {"recorded": False, "state": "publication_blocked",
                    "reasons": sorted(set(reasons)), "live_write_performed": False,
                    "real_writes_enabled": False}
        inserted = conn.execute(
            """INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,
                scheduled_at,status,publication_state,adapter_type,simulation_only,block_reasons,
                oauth_connection_id,live_stage)
            VALUES (%s,%s,%s,%s,now(),'queued','publication_queued','blogger_live',false,'[]',%s,'draft_needed')
            ON CONFLICT(idempotency_key) DO NOTHING
            RETURNING id,status,publication_state,adapter_type,simulation_only""",
            (row["policy_id"], request.blog_id, request.content_version_id,
             request.idempotency_key, target["oauth_connection_id"]),
        ).fetchone()
        if inserted is None:
            raise HTTPException(409, "Live publication request was concurrently registered")
        conn.execute(
            "INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details) VALUES (%s,'human_review_approved','publication_queued','live_eligibility_passed',%s)",
            (inserted["id"], Jsonb({"content_version_id": str(request.content_version_id),
                                    "oauth_connection_id": str(target["oauth_connection_id"]),
                                    "adapter_type": "blogger_live", "simulation_only": False})),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,blog_id,language_code,payload) VALUES ('publication.live_request.queued',%s,%s,%s)",
            (request.blog_id, row["blog_language"], Jsonb({
                "job_id": str(inserted["id"]), "content_version_id": str(request.content_version_id),
                "oauth_connection_id": str(target["oauth_connection_id"]),
                "adapter_type": "blogger_live", "simulation_only": False,
                "public_write_performed": False, "auto_enabled": False,
            })),
        )
        return {**dict(inserted), "duplicate": False, "public_write_performed": False,
                "auto_enabled": False}


@router.post("/{job_id}/simulate")
def simulate(job_id: UUID, request: SimulationInput) -> dict[str, Any]:
    with connection() as conn:
        job = conn.execute(
            "SELECT id,status,publication_state FROM publishing_jobs WHERE id=%s", (job_id,)
        ).fetchone()
        if job is None:
            raise HTTPException(404, "Publication request not found")
        existing = conn.execute(
            "SELECT * FROM publication_attempts WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone()
        if existing:
            if str(existing["job_id"]) != str(job_id) or existing["scenario"] != request.scenario:
                raise HTTPException(409, "Idempotency key conflict")
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('publication.mock.duplicate_blocked',%s)",
                (
                    Jsonb(
                        {
                            "job_id": str(job_id),
                            "attempt_id": str(existing["id"]),
                            "simulation_only": True,
                        }
                    ),
                ),
            )
            return {**dict(existing), "duplicate": True, "real_writes_enabled": False}
        result = FakeBloggerPublisher().publish(request.scenario)
        next_attempt = conn.execute(
            """SELECT COALESCE(max(attempt_no),0)+1 AS attempt_no FROM publication_attempts
            WHERE job_id=%s AND attempt_kind='interactive'""",
            (job_id,),
        ).fetchone()
        assert next_attempt is not None
        attempt_no = int(next_attempt["attempt_no"])
        if attempt_no > 4:
            raise HTTPException(429, "Mock simulation attempt limit reached")
        attempt = conn.execute(
            """INSERT INTO publication_attempts(job_id,idempotency_key,scenario,outcome,fake_post_id,
              result,attempt_no,attempt_kind,retryable) VALUES (%s,%s,%s,%s,%s,%s,%s,'interactive',%s)
              RETURNING *""",
            (
                job_id,
                request.idempotency_key,
                request.scenario,
                result["outcome"],
                result["fake_post_id"],
                Jsonb(result),
                attempt_no,
                request.scenario in {"timeout", "server_failure"},
            ),
        ).fetchone()
        assert attempt is not None
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('publication.mock.simulated',%s)",
            (
                Jsonb(
                    {
                        "job_id": str(job_id),
                        "attempt_id": str(attempt["id"]),
                        "scenario": request.scenario,
                        "outcome": result["outcome"],
                        "external_network_calls": 0,
                        "publication_state_unchanged": job["publication_state"],
                    }
                ),
            ),
        )
        return {
            **dict(attempt),
            "duplicate": False,
            "real_writes_enabled": False,
            "publication_state_unchanged": job["publication_state"],
        }


def _schedule_duplicate(
    conn: Any, job_id: UUID, key: str, action: str, when: datetime | None
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT job_id,action,scheduled_at,timezone FROM publication_schedule_events WHERE idempotency_key=%s",
        (key,),
    ).fetchone()
    if row is None:
        return None
    compatible_actions = (
        {"scheduled", "rescheduled"} if action in {"scheduled", "rescheduled"} else {action}
    )
    if str(row["job_id"]) != str(job_id) or row["action"] not in compatible_actions:
        raise HTTPException(409, "Idempotency key conflict")
    if when is not None and row["scheduled_at"] != when:
        raise HTTPException(409, "Idempotency key conflict")
    return {
        "job_id": str(job_id),
        "action": row["action"],
        "scheduled_at": row["scheduled_at"],
        "timezone": row["timezone"],
        "duplicate": True,
        "simulation_only": True,
        "real_writes_enabled": False,
    }


@router.put("/{job_id}/schedule")
def schedule_mock(job_id: UUID, request: ScheduleInput) -> dict[str, Any]:
    when = request.scheduled_at.astimezone(UTC)
    with connection() as conn:
        job = conn.execute(
            """SELECT id,status,publication_state,last_error_category FROM publishing_jobs
            WHERE id=%s AND simulation_only AND adapter_type='fake' FOR UPDATE""",
            (job_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(404, "Fake-only publication request not found")
        action = "rescheduled" if job["status"] == "queued" else "scheduled"
        duplicate = _schedule_duplicate(conn, job_id, request.idempotency_key, action, when)
        if duplicate:
            return duplicate
        if job["status"] not in {"blocked", "failed", "queued"}:
            raise HTTPException(409, "Request cannot be scheduled in its current lifecycle state")
        if job["status"] == "failed" and job["last_error_category"] not in {
            "timeout",
            "server_failure",
            "lease_expired",
        }:
            raise HTTPException(
                409, "Failure requires manual review and cannot be retried automatically"
            )
        conn.execute(
            """UPDATE publishing_jobs SET status='queued',scheduled_at=%s,available_at=%s,
              schedule_timezone=%s,mock_scenario=%s,lease_until=NULL,last_error_category=NULL,updated_at=now()
            WHERE id=%s""",
            (when, when, request.timezone, request.mock_scenario, job_id),
        )
        conn.execute(
            """INSERT INTO publication_schedule_events(job_id,idempotency_key,action,scheduled_at,timezone,details)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                job_id,
                request.idempotency_key,
                action,
                when,
                request.timezone,
                Jsonb(
                    {
                        "mock_scenario": request.mock_scenario,
                        "simulation_only": True,
                        "domain_state_unchanged": job["publication_state"],
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (
                "publication.mock." + action,
                Jsonb(
                    {
                        "job_id": str(job_id),
                        "scheduled_at": when.isoformat(),
                        "timezone": request.timezone,
                        "scenario": request.mock_scenario,
                        "domain_state_unchanged": job["publication_state"],
                        "simulation_only": True,
                    }
                ),
            ),
        )
        return {
            "job_id": str(job_id),
            "status": "queued",
            "publication_state": job["publication_state"],
            "scheduled_at": when,
            "timezone": request.timezone,
            "simulation_only": True,
            "real_writes_enabled": False,
            "eligible_for_real_publication": False,
        }


@router.delete("/{job_id}/schedule")
def cancel_schedule(job_id: UUID, request: CancelInput) -> dict[str, Any]:
    with connection() as conn:
        job = conn.execute(
            """SELECT id,status,publication_state FROM publishing_jobs
            WHERE id=%s AND simulation_only AND adapter_type='fake' FOR UPDATE""",
            (job_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(404, "Fake-only publication request not found")
        duplicate = _schedule_duplicate(conn, job_id, request.idempotency_key, "cancelled", None)
        if duplicate:
            return duplicate
        if job["status"] != "queued":
            raise HTTPException(409, "Only queued mock schedules can be cancelled")
        old_state = str(job["publication_state"])
        if not transition_allowed(old_state, "cancelled"):
            raise HTTPException(409, "Publication state cannot be cancelled")
        conn.execute(
            """UPDATE publishing_jobs SET status='cancelled',publication_state='cancelled',
            lease_until=NULL,updated_at=now() WHERE id=%s""",
            (job_id,),
        )
        conn.execute(
            """INSERT INTO publication_schedule_events(job_id,idempotency_key,action,timezone,details)
            VALUES (%s,%s,'cancelled','UTC',%s)""",
            (
                job_id,
                request.idempotency_key,
                Jsonb({"from_state": old_state, "simulation_only": True}),
            ),
        )
        conn.execute(
            """INSERT INTO publication_state_events(job_id,from_state,to_state,reason,details)
            VALUES (%s,%s,'cancelled','mock_schedule_cancelled',%s)""",
            (job_id, old_state, Jsonb({"simulation_only": True})),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('publication.mock.cancelled',%s)",
            (Jsonb({"job_id": str(job_id), "from_state": old_state, "simulation_only": True}),),
        )
        return {
            "job_id": str(job_id),
            "status": "cancelled",
            "publication_state": "cancelled",
            "simulation_only": True,
            "real_writes_enabled": False,
        }


@router.get("/worker")
def publication_worker_status() -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """SELECT service_name,process_id,status,last_error_category,last_seen_at,updated_at,execution_mode
            FROM worker_heartbeats WHERE service_name='publication_worker'"""
        ).fetchone()
        queue = conn.execute(
            """SELECT
              count(*) FILTER (WHERE simulation_only AND adapter_type='fake' AND status='queued')::int AS mock_queued,
              count(*) FILTER (WHERE simulation_only AND adapter_type='fake' AND status='queued'
                AND scheduled_at<=now() AND available_at<=now())::int AS mock_due,
              count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live' AND status='queued')::int AS live_queued,
              count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live' AND status='queued'
                AND scheduled_at<=now() AND available_at<=now())::int AS live_due,
              count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live' AND status='blocked')::int AS live_blocked,
              count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live' AND status='uncertain')::int AS live_uncertain
              ,count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live'
                AND publication_lane='scheduled_auto' AND status='queued')::int AS scheduled_auto_queued
              ,count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live'
                AND publication_lane='scheduled_auto' AND status='queued'
                AND scheduled_at<=now() AND available_at<=now())::int AS scheduled_auto_due
              ,count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live'
                AND publication_lane='manual' AND status='queued'
                AND EXISTS (SELECT 1 FROM manual_publication_approval_events a WHERE a.job_id=publishing_jobs.id))::int AS manual_confirmed_queued
              ,count(*) FILTER (WHERE NOT simulation_only AND adapter_type='blogger_live'
                AND publication_lane='manual' AND status='queued'
                AND scheduled_at<=now() AND available_at<=now()
                AND EXISTS (SELECT 1 FROM manual_publication_approval_events a WHERE a.job_id=publishing_jobs.id))::int AS manual_confirmed_due
            FROM publishing_jobs"""
        ).fetchone()
        queued_drafts = conn.execute(
            """SELECT count(*) AS n FROM blogger_write_operations
            WHERE operation='create_draft' AND status='pending'
              AND result->>'confirmation_recorded'='true'"""
        ).fetchone()
        mode = conn.execute(
            """SELECT configured_mode,daily_auto_limit,minimum_interval_minutes,emergency_stopped,
                operations_auto_approved FROM publication_mode_settings
              WHERE scope_type='global' AND scope_key=''"""
        ).fetchone()
        last_job = conn.execute(
            """SELECT id,status,publication_state,last_error_category,updated_at
              FROM publishing_jobs ORDER BY updated_at DESC,id DESC LIMIT 1"""
        ).fetchone()
        assert queue is not None
        assert queued_drafts is not None
        assert mode is not None
        heartbeat = dict(row) if row else None
        policy = _scheduled_auto_state(conn)
        capability = _live_write_capability(conn, policy, heartbeat, bool(mode["emergency_stopped"]))
        if int(queue["mock_due"]) > 0:
            idle_reason = None
        elif int(queue["live_due"]) > 0:
            idle_reason = "live_job_policy_blocked_or_lane_not_ready"
        elif int(queue["mock_queued"]) > 0 or int(queue["live_queued"]) > 0:
            idle_reason = "queued_jobs_not_yet_due"
        else:
            idle_reason = "no_queued_job_in_enabled_lane"
        return {
            "heartbeat": heartbeat,
            "heartbeat_fresh": bool(
                heartbeat and heartbeat.get("status") == "running" and heartbeat.get("last_seen_at")
                and datetime.now(UTC) - heartbeat["last_seen_at"] <= timedelta(seconds=45)
            ),
            "queue": dict(queue),
            "last_job": dict(last_job) if last_job else None,
            "idle_reason_if_processed_false": idle_reason,
            "global_mode": dict(mode),
            "auto_policy_active": False,
            "scheduled_auto_policy": policy,
            "scheduled_auto_queued": queue["scheduled_auto_queued"],
            "scheduled_auto_due": queue["scheduled_auto_due"],
            "manual_confirmed_queued": queue["manual_confirmed_queued"],
            "manual_confirmed_due": queue["manual_confirmed_due"],
            "queued_mock_jobs": queue["mock_queued"],
            "queued_confirmed_private_drafts": queued_drafts["n"],
            "private_draft_worker_available": True,
            "worker_execution_mode": capability["execution_mode"],
            "live_publication_dispatch_enabled": capability["live_dispatch"],
            "scheduled_auto_publication_enabled": capability["scheduled_auto"],
            "manual_confirmed_publication_enabled": capability["manual_confirmed"],
            "public_publication_enabled": bool(capability["scheduled_auto"] or capability["manual_confirmed"]),
            "real_writes_enabled": bool(capability["scheduled_auto"] or capability["manual_confirmed"]),
            "write_capability_reason": capability["reason"],
        }


@router.post("/blogs/{blog_id}/sync-readonly")
def sync_readonly(
    blog_id: UUID, page_token: str = Query(default="", max_length=2048)
) -> dict[str, Any]:
    remote = blogger_service.posts(blog_id, page_token, "live")
    items = remote.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(502, "Blogger returned an invalid post list")
    posts = [
        {key: item.get(key) for key in ("id", "url", "title", "status", "published", "updated")}
        for item in items
        if isinstance(item, dict)
    ]
    remote_ids = [str(post["id"]) for post in posts if post.get("id") is not None]
    with connection() as conn:
        registered = conn.execute(
            "SELECT id,language_code,url,blog_id FROM blogger_blogs WHERE id=%s", (blog_id,)
        ).fetchone()
        if registered is None:
            raise HTTPException(404, "Registered blog not found")
        records = (
            conn.execute(
                """SELECT remote_post_id,content_version_id FROM publishing_records
            WHERE blog_id=%s AND remote_post_id=ANY(%s)""",
                (blog_id, remote_ids),
            ).fetchall()
            if remote_ids
            else []
        )
        matched = {str(row["remote_post_id"]): row for row in records}
        result_posts = [
            {
                **post,
                "internal_record": str(post.get("id")) in matched,
                "content_version_id": str(matched[str(post["id"])]["content_version_id"])
                if post.get("id") is not None and str(post["id"]) in matched
                else None,
            }
            for post in posts
        ]
        conn.execute(
            """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
            VALUES ('publication.sync.checked',%s,%s,%s)""",
            (
                blog_id,
                registered["language_code"],
                Jsonb(
                    {
                        "read_only": True,
                        "post_count": len(result_posts),
                        "matched_internal_records": len(matched),
                        "next_page_available": bool(remote.get("nextPageToken")),
                        "discrepancies_require_manual_review": True,
                    }
                ),
            ),
        )
    return {
        "blog_id": registered["blog_id"],
        "blog_uuid": str(registered["id"]),
        "language_code": registered["language_code"],
        "posts": result_posts,
        "next_page_token": remote.get("nextPageToken", ""),
        "read_only": True,
        "internal_state_changed": False,
        "mock_rows_excluded": True,
        "real_writes_enabled": False,
    }
