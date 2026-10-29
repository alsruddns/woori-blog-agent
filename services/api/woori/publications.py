"""Fail-closed publication requests and explicitly offline mock simulations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import blogger_service
from .db import connection
from .publication_modes import (
    ModeSettingsInput,
    assess_auto_candidate,
    effective_mode,
    resolve_mode,
)

router = APIRouter(prefix="/admin/publications")

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
        }
    rows = conn.execute(
        """SELECT scope_type,scope_key,configured_mode,daily_auto_limit,
            minimum_interval_minutes,allowed_start_hour,allowed_end_hour,timezone,
            allowed_categories,excluded_topics,max_source_age_hours,retry_limit,
            emergency_stopped,operations_auto_approved,updated_at
        FROM publication_mode_settings ORDER BY CASE scope_type WHEN 'global' THEN 0
            WHEN 'language' THEN 1 ELSE 2 END,scope_key"""
    ).fetchall()
    items = [dict(row) for row in rows]
    languages = [dict(row) for row in conn.execute(
        "SELECT code,display_name,active FROM languages ORDER BY code"
    ).fetchall()]
    blogs = [dict(row) for row in conn.execute(
        "SELECT id,language_code,url,display_name,active FROM blogger_blogs ORDER BY language_code,url"
    ).fetchall()]
    global_setting = next((row for row in items if row["scope_type"] == "global"), None)
    return {
        "migration_required": False,
        "default_mode": "manual",
        "settings": items,
        "languages": languages,
        "blogs": blogs,
        "emergency_stopped": bool(global_setting and global_setting["emergency_stopped"]),
        "operations_auto_approved": False,
        "live_auto_enabled": False,
        "real_writes_enabled": False,
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


@router.put("/mode-settings")
def save_mode_settings(request: ModeSettingsInput) -> dict[str, Any]:
    with connection() as conn:
        current = _mode_settings(conn)
        if current["migration_required"]:
            raise HTTPException(409, "Publication settings migration 042 is required")
        if request.configured_mode == "auto":
            # Auto is a write-capable operating mode, not a preference-only
            # preview. Keep it unavailable until this release has a verified
            # live Publisher and an explicit operations approval path.
            raise HTTPException(
                409,
                detail={
                    "code": "auto_publication_unavailable",
                    "reasons": [
                        "live_blogger_publisher_not_enabled",
                        "operations_auto_approval_required",
                    ],
                    "real_writes_enabled": False,
                },
            )
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
    if row["human_review_required"] or not row["human_review_approved"]:
        reasons.append("human_review_pending")
    if not row.get("publication_approval_approved", False):
        reasons.append("publication_approval_missing_or_stale")
    if row["publish_ready"]:
        # Phase policy and schema deliberately prohibit this state today.
        reasons.append("unexpected_publish_ready_state")
    else:
        reasons.append("publish_ready_disabled")
    reasons.append("production_writes_disabled")
    if "machine_quality_not_passed" in reasons:
        state = "quality_held"
    elif "human_review_pending" in reasons:
        state = "human_review_pending"
    else:
        state = "publication_blocked"
    return {"state": state, "reasons": reasons}


def _candidate(conn: Any, version_id: UUID, blog_id: UUID) -> dict[str, Any] | None:
    return cast(
        dict[str, Any] | None,
        conn.execute(
            """SELECT v.id AS content_version_id,v.title,v.body,v.localization_id,
            l.language_code AS version_language,l.target_country,b.id AS blog_uuid,
            b.language_code AS blog_language,b.url,b.active AS blog_active,
            b.blog_id AS blog_id_value,b.connection_verified_at,b.test_publish_verified_at,
            lang.active AS language_active,g.status AS oauth_status,
            p.id AS policy_id,p.active AS policy_active,p.auto_publish_allowed,
            COALESCE(q.machine_passed,false) AS machine_passed,
            COALESCE(q.human_review_required,true) AS human_review_required,
            COALESCE(review.disposition='approved',false) AS human_review_approved,
            COALESCE(approval.action='approved' AND
              (editorial.id IS NULL OR approval.body_sha256=editorial.body_sha256),false)
              AS publication_approval_approved,
            COALESCE(q.publish_ready,false) AS publish_ready,
            q.id AS quality_evaluation_id,q.id AS evaluation_id,q.status AS quality_status,
            editorial.id AS editorial_version_id
        FROM content_versions v
        JOIN content_localizations l ON l.id=v.localization_id
        JOIN blogger_blogs b ON b.id=%s
        LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        JOIN languages lang ON lang.code=l.language_code
        LEFT JOIN language_profiles lp ON lp.language_code=l.language_code
          AND lp.target_country=l.target_country
        LEFT JOIN publishing_policies p ON p.blog_id=b.id AND p.profile_id=lp.id
        LEFT JOIN LATERAL (
          SELECT id,id AS evaluation_id,machine_passed,human_review_required,publish_ready,status
          FROM article_quality_evaluations WHERE content_version_id=v.id
          ORDER BY created_at DESC,id DESC LIMIT 1
        ) q ON true
        LEFT JOIN LATERAL (
          SELECT id,body_sha256 FROM article_editorial_versions
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


@router.get("")
def list_publications() -> dict[str, Any]:
    with connection() as conn:
        mode_data = _mode_settings(conn)
        candidates = conn.execute(
            """SELECT v.id AS content_version_id,v.title,l.language_code,
                l.target_country,b.id AS blog_id,b.url,b.blog_id AS blogger_blog_id,
                v.created_at AS version_created_at,
                COALESCE(q.machine_passed,false) AS machine_passed,
                COALESCE(q.human_review_required,true) AS human_review_required,
                COALESCE(q.publish_ready,false) AS publish_ready,q.status AS quality_status,
                q.evaluation_id,
                q.created_at AS evaluated_at,
                COALESCE(review.disposition='approved',false) AS editorial_review_approved,
                COALESCE(approval.action='approved' AND
                    (editorial.id IS NULL OR approval.body_sha256=editorial.body_sha256),false)
                    AS publication_approval_approved
            FROM content_versions v JOIN content_localizations l ON l.id=v.localization_id
            JOIN blogger_blogs b ON b.language_code=l.language_code AND b.active
            LEFT JOIN LATERAL (SELECT id AS evaluation_id,machine_passed,human_review_required,publish_ready,status,created_at
                FROM article_quality_evaluations WHERE content_version_id=v.id
                ORDER BY created_at DESC,id DESC LIMIT 1) q ON true
            LEFT JOIN LATERAL (
                SELECT id,body_sha256 FROM article_editorial_versions
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
            ORDER BY v.created_at DESC LIMIT 100"""
        ).fetchall()
        jobs = conn.execute(
            """SELECT j.id,j.content_version_id,j.blog_id,b.language_code,b.url,
                j.status,j.publication_state,j.scheduled_at,j.schedule_timezone,j.block_reasons,
                j.attempts,j.retry_count,j.last_error_category,j.updated_at,
                (SELECT q.evaluation_id FROM article_quality_evaluations q
                 WHERE q.content_version_id=j.content_version_id
                 ORDER BY q.created_at DESC,q.id DESC LIMIT 1) AS evaluation_id,
                (SELECT count(*) FROM publication_attempts a WHERE a.job_id=j.id) AS simulation_count
            FROM publishing_jobs j JOIN blogger_blogs b ON b.id=j.blog_id
            ORDER BY j.scheduled_at DESC,j.id DESC LIMIT 100"""
        ).fetchall()
        attempts = conn.execute(
            "SELECT id,job_id,scenario,outcome,fake_post_id,result,created_at FROM publication_attempts ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
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
        for candidate in candidates:
            candidate["mode_policy"] = resolve_mode(
                mode_data["settings"], str(candidate["language_code"]), str(candidate["blog_id"])
            )
            candidate["effective_mode"] = effective_mode(
                candidate["mode_policy"]["configured_mode"],
                emergency_stopped=bool(mode_data["emergency_stopped"]),
            )
            candidate["auto_eligibility"] = assess_auto_candidate(
                {
                    "machine_passed": candidate["machine_passed"],
                    "publish_ready": candidate["publish_ready"],
                    "editorial_review_passed": candidate["editorial_review_approved"],
                },
                requested_mode=candidate["mode_policy"]["configured_mode"],
                emergency_stopped=bool(mode_data["emergency_stopped"]),
            )
        return {
            "candidates": [dict(row) for row in candidates],
            "jobs": [dict(row) for row in jobs],
            "simulations": [dict(row) for row in attempts],
            "worker": dict(worker) if worker else None,
            "queued_mock_jobs": queued["n"],
            "queued_confirmed_private_drafts": queued_drafts["n"],
            "real_writes_enabled": False,
            "publish_ready_enabled": False,
            "adapter_available": "fake_and_confirmed_private_draft_worker",
            "mode_policy": mode_data,
            "auto_candidate_count": sum(
                1 for candidate in candidates if candidate["auto_eligibility"]["eligible"]
            ),
            "auto_runtime_status": "disabled_pending_separate_operations_approval",
        }


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
            """SELECT service_name,process_id,status,last_error_category,last_seen_at,updated_at
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
        return {
            "heartbeat": dict(row) if row else None,
            "queued_mock_jobs": queued["n"],
            "queued_confirmed_private_drafts": queued_drafts["n"],
            "private_draft_worker_available": True,
            "public_publication_enabled": False,
            "real_writes_enabled": False,
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
