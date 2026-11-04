"""Independent persisted operator controls. No setting confers editorial approval."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import connection


def authoring_permission(*, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Service-owned lookup, no Dashboard dependency or credential output."""
    from .config import settings

    try:
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=3, transport=transport
        ) as client:
            response = client.get(
                "http://127.0.0.1:8100/admin/automation-controls",
                headers={"Authorization": "Bearer " + settings().admin_token},
            )
        if response.status_code in {401, 403}:
            return {
                "allowed": False,
                "reason": "automation_policy_access_denied",
                "source": "backend_api",
            }
        if response.status_code != 200:
            raise ValueError("backend_unavailable")
        state = response.json()["settings"]
        if (
            type(state.get("auto_manuscript_enabled")) is not bool
            or type(state.get("revision")) is not int
            or state["revision"] < 1
        ):
            raise ValueError("invalid_policy_response")
        enabled = state["auto_manuscript_enabled"] is True
        return {
            "allowed": enabled,
            "revision": state["revision"],
            "reason": None if enabled else "automatic_authoring_disabled",
            "source": "backend_api",
        }
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        try:
            with connection() as conn:
                state = read(conn)
            enabled = state["auto_manuscript_enabled"] is True
            return {
                "allowed": enabled,
                "revision": state["revision"],
                "reason": None if enabled else "automatic_authoring_disabled",
                "source": "repository",
            }
        except (OSError, ValueError, RuntimeError, psycopg.Error):
            return {
                "allowed": False,
                "reason": "automation_policy_unavailable",
                "source": "unavailable",
            }


VERSION = "automation-controls/3"
router = APIRouter(prefix="/admin/automation-controls")


def read(conn: Any, *, lock: bool = False) -> dict[str, Any]:
    row = conn.execute(
        """SELECT c.*,t.enabled AS trends_collection_enabled,t.interval_minutes,
        p.emergency_stopped AS emergency_stop,p.blogger_api_restricted,
        p.configured_mode,p.operations_auto_approved,p.blogger_write_mode
        FROM automation_controls c CROSS JOIN trend_collection_settings t
        CROSS JOIN publication_mode_settings p
        WHERE c.id=1 AND t.id=1 AND p.scope_type='global' AND p.scope_key=''
        """
        + (" FOR SHARE OF c,p,t" if lock else "")
    ).fetchone()
    if not row:
        raise RuntimeError("automation_controls_unavailable")
    return dict(row)


def allowed(key: str) -> bool:
    if key not in {
        "auto_manuscript_enabled",
        "trends_collection_enabled",
        "auto_publishing_enabled",
        "manual_publishing_enabled",
        "trends_auto_publishing_enabled",
        "scheduled_auto_publishing_enabled",
        "automatic_publication_operator_approved",
    }:
        return False
    try:
        with connection() as conn:
            return bool(read(conn)[key])
    except (psycopg.Error, OSError, RuntimeError):
        return False


def acknowledge(conn: Any, service: str, pid: int) -> None:
    state = read(conn)
    conn.execute(
        """INSERT INTO automation_runtime_ack(service_name,process_id,revision,engine_version,last_seen_at)
        VALUES(%s,%s,%s,%s,clock_timestamp()) ON CONFLICT(service_name) DO UPDATE SET
        process_id=EXCLUDED.process_id,revision=EXCLUDED.revision,engine_version=EXCLUDED.engine_version,last_seen_at=EXCLUDED.last_seen_at""",
        (service, pid, state["revision"], VERSION),
    )


@router.get("")
def snapshot() -> dict[str, Any]:
    with connection() as conn:
        state = read(conn)
        workers = conn.execute(
            """SELECT h.service_name,h.process_id,h.status,h.last_seen_at,
            a.revision AS applied_revision,a.engine_version,a.last_seen_at AS policy_seen_at,
            (a.process_id=h.process_id AND a.revision=%s AND a.last_seen_at>now()-interval '45 seconds'
             AND h.status='running' AND h.last_seen_at>now()-interval '45 seconds'
             AND (h.service_name<>'publication_worker' OR a.engine_version=%s)) AS policy_applied
            FROM worker_heartbeats h LEFT JOIN automation_runtime_ack a USING(service_name)""",
            (state["revision"], VERSION),
        ).fetchall()
        history = conn.execute(
            "SELECT id,created_at,payload FROM audit_events WHERE event_type='automation.controls.changed' ORDER BY id DESC LIMIT 25"
        ).fetchall()
        blogs = conn.execute(
            "SELECT id,display_name,language_code,url FROM blogger_blogs WHERE active ORDER BY language_code,display_name"
        ).fetchall()
        recent = conn.execute("""SELECT
            (SELECT max(collected_at) FROM trend_observations) AS last_collection,
            (SELECT max(received_at) FROM external_content_imports) AS last_import,
            (SELECT max(started_at) FROM codex_authoring_jobs) AS last_authoring,
            (SELECT count(*) FROM codex_authoring_jobs WHERE state='queued') AS authoring_queued,
            (SELECT count(*) FROM codex_authoring_jobs WHERE state IN ('researching','writing','validating')) AS authoring_running,
            (SELECT count(DISTINCT geo) FROM trend_collection_slots) AS region_count""").fetchone()
        job_count = conn.execute(
            """SELECT count(*) AS n FROM publishing_jobs j
            JOIN automation_publication_grants g ON g.job_id=j.id
            WHERE j.status='queued' AND ((g.lane='auto' AND g.epoch=%s AND %s AND
                ((g.manuscript_origin='google_trends' AND %s AND g.source_epoch=%s)
                 OR (g.manuscript_origin='scheduled' AND %s AND g.source_epoch=%s)))
              OR (g.lane='manual' AND g.epoch=%s AND %s))""",
            (
                state["auto_epoch"],
                state["auto_publishing_enabled"],
                state["trends_auto_publishing_enabled"],
                state["trends_auto_epoch"],
                state["scheduled_auto_publishing_enabled"],
                state["scheduled_auto_epoch"],
                state["manual_epoch"],
                state["manual_publishing_enabled"],
            ),
        ).fetchone()
        last_publication = conn.execute(
            "SELECT remote_status,remote_url,remote_verified_at FROM publishing_records ORDER BY remote_verified_at DESC NULLS LAST LIMIT 1"
        ).fetchone()
        scheduled_policy = conn.execute(
            "SELECT action,approved_blog_ids FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        pending_auto_jobs = conn.execute(
            "SELECT count(*)::int AS n FROM publishing_jobs WHERE NOT simulation_only "
            "AND publication_lane IN ('scheduled_auto','trends_auto') AND status='queued'"
        ).fetchone()
    from . import external_policy

    owner_cost_approval = external_policy._blogger_policy_approval() is not None
    public_approval = external_policy._blogger_public_publish_approval()
    owner_public_approval = bool(
        public_approval
        and sorted(public_approval["approved_blog_ids"])
            == sorted(str(value) for value in state["auto_blog_ids"])
    )
    approval_blockers: list[str] = []
    if not state["automatic_publication_operator_approved"]:
        approval_blockers.append("operator_auto_publication_approval_off")
    if not state["auto_publishing_enabled"]:
        approval_blockers.append("global_auto_publication_off")
    if not (state["trends_auto_publishing_enabled"] or state["scheduled_auto_publishing_enabled"]):
        approval_blockers.append("no_automatic_publication_route_enabled")
    if state["emergency_stop"]:
        approval_blockers.append("emergency_stop_enabled")
    if state["blogger_api_restricted"]:
        approval_blockers.append("blogger_api_restricted")
    if not owner_cost_approval:
        approval_blockers.append("external_blogger_cost_policy_approval_missing")
    if public_approval is None:
        approval_blockers.append("external_blogger_public_write_approval_missing")
    elif not owner_public_approval:
        approval_blockers.append("external_blogger_public_write_approval_scope_mismatch")
    if state["blogger_write_mode"] != "public_write_approved":
        approval_blockers.append("blogger_write_mode_not_public_write_approved")
    if not state["operations_auto_approved"]:
        approval_blockers.append("legacy_publication_operations_approval_unavailable")
    blocked = (
        "긴급 정지로 차단"
        if state["emergency_stop"]
        else "Google API 제한으로 차단"
        if state["blogger_api_restricted"]
        else None
    )
    applied = {w["service_name"]: bool(w["policy_applied"]) for w in workers}
    effective = {}
    for key, worker in [
        ("trends_collection_enabled", "research_worker"),
        ("auto_manuscript_enabled", "research_worker"),
        ("auto_publishing_enabled", "publication_worker"),
        ("manual_publishing_enabled", "publication_worker"),
        ("trends_auto_publishing_enabled", "publication_worker"),
        ("scheduled_auto_publishing_enabled", "publication_worker"),
        ("automatic_publication_operator_approved", "publication_worker"),
    ]:
        effective[key] = (
            "신규 실행 중지"
            if not state[key]
            else "전체 자동 발행 OFF로 차단 중"
            if key in {"trends_auto_publishing_enabled", "scheduled_auto_publishing_enabled"}
            and not state["auto_publishing_enabled"]
            else "예약 발행 승인 범위 확인 필요"
            if key == "scheduled_auto_publishing_enabled"
            and (not scheduled_policy or scheduled_policy["action"] != "enabled"
                 or not {str(value) for value in state["auto_blog_ids"]}.issubset(
                     {str(value) for value in scheduled_policy["approved_blog_ids"]}))
            else blocked
            if "publishing" in key and blocked
            else "정상"
            if applied.get(worker)
            else "Worker 적용 대기 또는 연결 실패"
        )
    if not state["automatic_publication_operator_approved"]:
        effective["automatic_publication_operator_approved"] = "자동 발행 운영 승인 OFF — 자동 발행 중지"
    elif approval_blockers:
        effective["automatic_publication_operator_approved"] = "운영 승인 ON — 다른 정책 조건으로 발행 차단"
    elif not applied.get("publication_worker"):
        effective["automatic_publication_operator_approved"] = "운영 승인 저장 — Worker 적용 대기"
    else:
        effective["automatic_publication_operator_approved"] = "자동 발행 운영 허용 — 적격 원고 대기"
    return {
        "settings": state,
        "effective": effective,
        "workers": workers,
        "history": history,
        "blogs": blogs,
        "recent": recent,
        "eligible_jobs": job_count["n"]
        if job_count and not blocked and applied.get("publication_worker")
        and state["automatic_publication_operator_approved"]
        else 0,
        "last_publication": last_publication,
        "automatic_publication_approval": {
            "approved": bool(state["automatic_publication_operator_approved"]),
            "effective": bool(state["automatic_publication_operator_approved"] and not approval_blockers
                               and applied.get("publication_worker")),
            "worker_applied": bool(applied.get("publication_worker")),
            "blockers": approval_blockers,
            "pending_auto_jobs": int(pending_auto_jobs["n"] if pending_auto_jobs else 0),
            "legacy_operations_auto_approved": bool(state["operations_auto_approved"]),
            "configured_mode": state["configured_mode"],
            "blogger_write_mode": state["blogger_write_mode"],
            "external_cost_policy_approved": owner_cost_approval,
            "external_public_write_approved": owner_public_approval,
            "scope": state["automatic_publication_approval_scope"],
            "actor": state["automatic_publication_approval_actor"],
            "reason": state["automatic_publication_approval_reason"],
            "changed_at": state["automatic_publication_approval_changed_at"],
        },
        "api_engine_version": VERSION,
        "scheduled_policy_enabled": bool(scheduled_policy and scheduled_policy["action"] == "enabled"),
        "google_write_verified": False,
        "google_write_verification_note": "읽기 성공 또는 사용자 제한 해제 확인은 쓰기 성공의 증거가 아닙니다.",
    }


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    actor: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=10, max_length=500)
    trends_collection_enabled: bool | None = None
    auto_manuscript_enabled: bool | None = None
    auto_publishing_enabled: bool | None = None
    manual_publishing_enabled: bool | None = None
    trends_auto_publishing_enabled: bool | None = None
    scheduled_auto_publishing_enabled: bool | None = None
    automatic_publication_operator_approved: bool | None = None
    global_publish_min_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    trends_authoring_min_volume: int | None = Field(default=None, ge=1, le=1_000_000_000)
    emergency_stop: bool | None = None
    auto_mode: Literal["draft", "publish"] | None = None
    auto_blog_ids: list[str] | None = None
    confirm_auto: bool = False
    confirm_live: bool = False
    confirm_emergency_release: bool = False
    confirm_operator_auto_approval: bool = False
    google_account_available: bool | None = None

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("actor_must_contain_at_least_two_characters")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("reason_must_contain_at_least_ten_characters")
        return value


class PublicLiveApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    actor: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=10, max_length=500)
    approved_blog_ids: list[UUID] = Field(min_length=6, max_length=6)
    confirm_public_live: bool
    confirm_billing_quota_reviewed: bool

    @field_validator("approved_blog_ids", mode="before")
    @classmethod
    def parse_approved_blog_ids(cls, value: Any) -> Any:
        # UUID identifiers arrive as JSON strings from the Dashboard. Keep
        # strict validation for every other field while parsing that wire form.
        if isinstance(value, list):
            return [UUID(item) if isinstance(item, str) else item for item in value]
        return value

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("actor_must_contain_at_least_two_characters")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("reason_must_contain_at_least_ten_characters")
        return value


PUBLIC_LIVE_LANGUAGES = {"en", "ko", "ja", "de", "pt-BR", "vi"}


def _scheduled_import_review_counts(conn: Any) -> dict[str, int]:
    row = conn.execute(
        """SELECT count(*)::int AS total,
        count(*) FILTER (WHERE state='awaiting_human_review')::int AS awaiting_human_review
        FROM external_content_imports WHERE generation_method='chatgpt_scheduled_export'"""
    ).fetchone()
    if not row:
        raise RuntimeError("scheduled_import_counts_unavailable")
    return dict(row)


@router.post("/approve-public-live")
def approve_public_live(request: PublicLiveApproval) -> dict[str, Any]:
    """Record exact-blog LIVE consent and atomically activate its current runtime policy."""
    if request.confirm_public_live is not True or request.confirm_billing_quota_reviewed is not True:
        raise HTTPException(422, "Explicit LIVE and Billing/quota confirmations are required")
    target_ids = sorted({str(value) for value in request.approved_blog_ids})
    if len(target_ids) != 6:
        raise HTTPException(422, "Exactly the six existing approved Blogger IDs are required")
    from . import external_policy

    if external_policy.billing_credential_names():
        raise HTTPException(409, "Potentially billable credentials block Blogger LIVE writes")
    if external_policy._blogger_policy_approval() is None:
        raise HTTPException(409, "Existing Blogger zero-cost policy attestation is unavailable")

    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(20261102,103)")
        before = read(conn, lock=True)
        if before["revision"] != request.expected_revision:
            raise HTTPException(409, "Automation controls changed; reload the current revision")
        active_blogs = conn.execute(
            """SELECT b.id,b.language_code,g.status AS oauth_status,g.scopes
            FROM blogger_blogs b JOIN google_connections g ON g.id=b.oauth_connection_id
            WHERE b.id=ANY(%s::uuid[]) AND b.active ORDER BY b.id""",
            (request.approved_blog_ids,),
        ).fetchall()
        if (len(active_blogs) != 6 or {str(row["id"]) for row in active_blogs} != set(target_ids)
                or {row["language_code"] for row in active_blogs} != PUBLIC_LIVE_LANGUAGES
                or any(row["oauth_status"] != "connected"
                       or list(row["scopes"] or []) != ["https://www.googleapis.com/auth/blogger"]
                       for row in active_blogs)):
            raise HTTPException(422, "Approval scope must match the six active Blogger-connected EN/KO/JA/DE/pt-BR/VI blogs")
        if sorted(str(value) for value in before["auto_blog_ids"]) != target_ids:
            raise HTTPException(409, "Configured automatic Blogger scope differs from the requested six blogs")
        if not (before["auto_publishing_enabled"] and before["automatic_publication_operator_approved"]
                and before["auto_mode"] == "publish" and before["scheduled_auto_publishing_enabled"]
                and before["trends_auto_publishing_enabled"]):
            raise HTTPException(409, "Existing global, LIVE, scheduled and Trends controls must already be enabled")
        if before["emergency_stop"] or before["blogger_api_restricted"]:
            raise HTTPException(409, "Emergency stop or Blogger API restriction is active")
        if before["global_publish_min_interval_minutes"] != 15 or before["global_daily_live_publish_limit"] != 100:
            raise HTTPException(409, "Required 15-minute and 100/day LIVE limits are not in effect")
        scheduled_policy = conn.execute(
            "SELECT action,approved_blog_ids,daily_limit FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if (not scheduled_policy or scheduled_policy["action"] != "enabled"
                or set(target_ids) != {str(value) for value in scheduled_policy["approved_blog_ids"]}
                or scheduled_policy["daily_limit"] != 100):
            raise HTTPException(409, "Existing scoped Scheduled Auto policy is not active for the six blogs")
        queue = conn.execute(
            """SELECT count(*) FILTER (WHERE NOT simulation_only AND status='queued')::int AS queued,
            count(*) FILTER (WHERE NOT simulation_only AND status IN ('running','uncertain'))::int AS in_flight
            FROM publishing_jobs"""
        ).fetchone()
        assert queue is not None
        if queue["queued"] or queue["in_flight"]:
            raise HTTPException(409, "Publication queue or in-flight Blogger job must drain before activation")
        writes = conn.execute(
            """SELECT
            (SELECT count(*)::int FROM blogger_write_operations WHERE status='pending') AS pending_operations,
            (SELECT count(*)::int FROM live_publication_attempts WHERE outcome='requested') AS requested_attempts"""
        ).fetchone()
        assert writes is not None
        if writes["pending_operations"] or writes["requested_attempts"]:
            raise HTTPException(409, "Pending Blogger write operation or uncertain in-flight attempt must resolve before activation")
        import_count = _scheduled_import_review_counts(conn)
        if import_count["total"] != 24 or import_count["awaiting_human_review"] != 24:
            raise HTTPException(409, "Scheduled Import review-state precondition changed")
        categories = [row["slug"] for row in conn.execute("SELECT slug FROM categories ORDER BY slug").fetchall()]
        if not categories:
            raise HTTPException(409, "Registered publication category allowlist is unavailable")

        from uuid import uuid4

        approval_id = str(uuid4())
        scope = {
            "blog_ids": target_ids,
            "languages": sorted(PUBLIC_LIVE_LANGUAGES),
            "publication_mode": "auto",
            "daily_live_limit_kst": 100,
            "minimum_interval_minutes": 15,
            "scheduled_daily_limit": 100,
            "priority": ["scheduled", "manual", "trends"],
            "zh-CN": "denied",
        }
        conn.execute(
            """INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)""",
            (external_policy.BLOGGER_PUBLIC_APPROVAL_EVENT, Jsonb({
                "approval_id": approval_id,
                "provider": "google_blogger_read",
                "policy_version": 1,
                "actor": "project_owner_explicit_public_publish_approval",
                "operator_actor": request.actor,
                "reason": request.reason,
                "evidence": "I_APPROVE_BLOGGER_PUBLIC_PUBLISH",
                "approved_scope": ["public_post_publish"],
                "approved_blog_ids": target_ids,
                "approved_languages": sorted(PUBLIC_LIVE_LANGUAGES),
                "billing_quota_reviewed_and_confirmed": True,
                "cloud_console_approval_required": False,
                "scope": scope,
                "existing_imports_reactivated": False,
                "existing_jobs_reauthorized": False,
                "actual_blogger_write_performed": False,
            })),
        )
        mode = conn.execute(
            """UPDATE publication_mode_settings SET configured_mode='auto',daily_auto_limit=100,
            minimum_interval_minutes=15,timezone='Asia/Seoul',allowed_categories=%s,
            operations_auto_approved=true,blogger_write_mode='public_write_approved',updated_at=clock_timestamp()
            WHERE scope_type='global' AND scope_key=''
            RETURNING configured_mode,daily_auto_limit,minimum_interval_minutes,operations_auto_approved,blogger_write_mode""",
            (categories,),
        ).fetchone()
        if not mode:
            raise HTTPException(503, "Global publication settings are unavailable")
        conn.execute(
            """UPDATE automation_controls SET auto_epoch=gen_random_uuid(),auto_enabled_at=clock_timestamp(),
            trends_auto_epoch=gen_random_uuid(),trends_auto_enabled_at=clock_timestamp(),
            scheduled_auto_epoch=gen_random_uuid(),scheduled_auto_enabled_at=clock_timestamp(),
            automatic_publication_approval_actor=%s,automatic_publication_approval_reason=%s,
            automatic_publication_approval_changed_at=clock_timestamp(),automatic_publication_approval_scope=%s::jsonb,
            revision=revision+1,updated_at=clock_timestamp() WHERE id=1""",
            (request.actor, request.reason, Jsonb(scope)),
        )
        saved = read(conn)
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('publication.mode.changed',%s)",
            (Jsonb({"actor": request.actor, "reason": request.reason, "scope_type": "global",
                "configured_mode": "auto", "effective_mode": "auto", "live_auto_enabled": False,
                "worker_ack_pending": True, "real_writes_enabled": False, "operations_auto_approved": True,
                "blogger_write_mode": "public_write_approved", "allowed_blog_ids": target_ids,
                "allowed_categories": categories, "daily_live_limit_kst": 100,
                "minimum_interval_minutes": 15, "migration_version": 91}),),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('automation.controls.changed',%s)",
            (Jsonb({"actor": request.actor, "reason": request.reason,
                "revision": saved["revision"], "changed_fields": ["publication_mode_settings", "auto_epoch",
                    "trends_auto_epoch", "scheduled_auto_epoch", "automatic_publication_approval_scope"],
                "auto_blog_ids": target_ids, "queue_before": {**dict(queue), **dict(writes)},
                "scheduled_imports": dict(import_count), "old_jobs_reauthorized": False,
                "existing_imports_reactivated": False, "worker_ack": "pending"}),),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('automation.operator_publication_approval.changed',%s)",
            (Jsonb({"previous_approval": True, "new_approval": True, "actor": request.actor,
                "reason": request.reason, "revision": saved["revision"], "approved_scope": scope,
                "billing_quota_reviewed_and_confirmed": True, "result": "persisted_worker_ack_pending"}),),
        )
    return {"saved": True, "approval_id": approval_id, "revision": saved["revision"],
        "configured_mode": mode["configured_mode"], "AutoMode": mode["configured_mode"],
        "AutoPolicyActive": False, "application": "pending_worker_ack",
        "approved_blog_ids": target_ids, "blogger_write_performed": False}


@router.put("")
def change(request: Change) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(20261102,103)")
        before = read(conn, lock=True)
        if before["revision"] != request.expected_revision:
            raise HTTPException(409, "설정이 변경되었습니다. 최신 상태를 다시 불러오세요.")
        after = {
            **before,
            **request.model_dump(
                exclude_none=True,
                exclude={
                    "actor",
                    "reason",
                    "expected_revision",
                    "confirm_auto",
                    "confirm_live",
                    "confirm_emergency_release",
                    "confirm_operator_auto_approval",
                    "google_account_available",
                },
            ),
        }
        before["auto_blog_ids"] = [str(x) for x in before["auto_blog_ids"]]
        after["auto_blog_ids"] = sorted({str(x) for x in after["auto_blog_ids"]})
        before["auto_blog_ids"] = sorted(before["auto_blog_ids"])
        auto_changed = any(
            after[k] != before[k] for k in ("auto_publishing_enabled", "auto_mode", "auto_blog_ids")
        )
        route_changes = {
            route: after[route + "_auto_publishing_enabled"]
            != before[route + "_auto_publishing_enabled"]
            for route in ("trends", "scheduled")
        }
        operator_approval_changed = (
            after["automatic_publication_operator_approved"]
            != before["automatic_publication_operator_approved"]
        )
        if operator_approval_changed and not request.confirm_operator_auto_approval:
            raise HTTPException(422, "자동 발행 운영 승인 변경은 적용 범위 확인이 필요합니다.")
        if after["auto_mode"] == "publish" and before["auto_mode"] != "publish" and not request.confirm_live:
            raise HTTPException(422, "LIVE 자동 공개에 대한 별도 확인이 필요합니다.")
        if after["auto_blog_ids"] != before["auto_blog_ids"]:
            try:
                scope_targets = [UUID(str(x)) for x in after["auto_blog_ids"]]
            except ValueError:
                raise HTTPException(422, "잘못된 Blogger 식별자입니다.") from None
            scope_count = conn.execute(
                "SELECT count(*) n FROM blogger_blogs WHERE id=ANY(%s::uuid[]) AND active",
                (scope_targets,),
            ).fetchone()
            if not scope_count or scope_count["n"] != len(scope_targets):
                raise HTTPException(422, "활성 등록 Blogger만 선택할 수 있습니다.")
        for route, changed in route_changes.items():
            if changed and after[route + "_auto_publishing_enabled"]:
                if not request.confirm_auto:
                    raise HTTPException(422, "경로별 자동 발행 활성화 범위를 확인해야 합니다.")
                if after["auto_mode"] == "publish" and not request.confirm_live:
                    raise HTTPException(422, "LIVE 자동 공개를 별도로 확인해야 합니다.")
        if after["auto_publishing_enabled"] and auto_changed:
            if not request.confirm_auto or not after["auto_blog_ids"]:
                raise HTTPException(422, "대상 Blogger와 자동 발행 범위 확인이 필요합니다.")
            if after["auto_mode"] == "publish" and not request.confirm_live:
                raise HTTPException(422, "LIVE 자동 공개에 대한 별도 확인이 필요합니다.")
            try:
                targets = [UUID(str(x)) for x in after["auto_blog_ids"]]
            except ValueError:
                raise HTTPException(422, "잘못된 Blogger 식별자입니다.") from None
            counted = conn.execute(
                "SELECT count(*) n FROM blogger_blogs WHERE id=ANY(%s::uuid[]) AND active",
                (targets,),
            ).fetchone()
            count = counted["n"] if counted else 0
            if count != len(set(targets)):
                raise HTTPException(422, "활성 등록 Blogger만 선택할 수 있습니다.")
        if (
            before["emergency_stop"]
            and not after["emergency_stop"]
            and not request.confirm_emergency_release
        ):
            raise HTTPException(422, "긴급 정지 해제를 명시적으로 확인해야 합니다.")
        pending_auto_jobs = conn.execute(
            "SELECT count(*)::int AS n FROM publishing_jobs WHERE NOT simulation_only "
            "AND publication_lane IN ('scheduled_auto','trends_auto') AND status='queued'"
        ).fetchone()
        approval_scope = {
            "global_auto_publication_enabled": bool(after["auto_publishing_enabled"]),
            "trends_auto_publication_enabled": bool(after["trends_auto_publishing_enabled"]),
            "scheduled_auto_publication_enabled": bool(after["scheduled_auto_publishing_enabled"]),
            "publication_mode": after["auto_mode"],
            "blog_ids": [str(value) for value in after["auto_blog_ids"]],
            "minimum_interval_minutes": int(after["global_publish_min_interval_minutes"]),
            "daily_live_limit": int(after["global_daily_live_publish_limit"]),
            "emergency_stop": bool(after["emergency_stop"]),
            "blogger_api_restricted": bool(after["blogger_api_restricted"]),
            "legacy_operations_auto_approved": bool(after["operations_auto_approved"]),
            "configured_mode": after["configured_mode"],
            "blogger_write_mode": after["blogger_write_mode"],
        }
        conn.execute(
            """UPDATE automation_controls SET auto_manuscript_enabled=%s,auto_publishing_enabled=%s,
            manual_publishing_enabled=%s,auto_mode=%s,auto_blog_ids=%s::uuid[],
            trends_auto_publishing_enabled=%s,scheduled_auto_publishing_enabled=%s,
            automatic_publication_operator_approved=%s,
            automatic_publication_approval_actor=CASE WHEN %s THEN %s ELSE automatic_publication_approval_actor END,
            automatic_publication_approval_reason=CASE WHEN %s THEN %s ELSE automatic_publication_approval_reason END,
            automatic_publication_approval_changed_at=CASE WHEN %s THEN clock_timestamp() ELSE automatic_publication_approval_changed_at END,
            automatic_publication_approval_scope=CASE WHEN %s THEN %s::jsonb ELSE automatic_publication_approval_scope END,
            global_publish_min_interval_minutes=%s,trends_authoring_min_volume=%s,
            trends_auto_epoch=CASE WHEN %s THEN gen_random_uuid() ELSE trends_auto_epoch END,
            trends_auto_enabled_at=CASE WHEN %s THEN clock_timestamp() ELSE trends_auto_enabled_at END,
            scheduled_auto_epoch=CASE WHEN %s THEN gen_random_uuid() ELSE scheduled_auto_epoch END,
            scheduled_auto_enabled_at=CASE WHEN %s THEN clock_timestamp() ELSE scheduled_auto_enabled_at END,
            auto_epoch=CASE WHEN %s THEN gen_random_uuid() ELSE auto_epoch END,
            auto_enabled_at=CASE WHEN %s THEN clock_timestamp() ELSE auto_enabled_at END,
            manual_epoch=CASE WHEN %s THEN gen_random_uuid() ELSE manual_epoch END,
            manual_enabled_at=CASE WHEN %s THEN clock_timestamp() ELSE manual_enabled_at END,
            google_account_report=CASE WHEN %s::boolean IS NULL THEN google_account_report WHEN %s THEN 'user_reported_available' ELSE 'restricted' END,
            revision=revision+1,updated_at=clock_timestamp() WHERE id=1""",
            (
                after["auto_manuscript_enabled"],
                after["auto_publishing_enabled"],
                after["manual_publishing_enabled"],
                after["auto_mode"],
                [str(x) for x in after["auto_blog_ids"]],
                after["trends_auto_publishing_enabled"],
                after["scheduled_auto_publishing_enabled"],
                after["automatic_publication_operator_approved"],
                operator_approval_changed,
                request.actor.strip(),
                operator_approval_changed,
                request.reason.strip(),
                operator_approval_changed,
                operator_approval_changed,
                Jsonb(approval_scope),
                after["global_publish_min_interval_minutes"],
                after["trends_authoring_min_volume"],
                route_changes["trends"],
                route_changes["trends"],
                route_changes["scheduled"],
                route_changes["scheduled"],
                auto_changed,
                auto_changed,
                after["manual_publishing_enabled"] != before["manual_publishing_enabled"],
                after["manual_publishing_enabled"] != before["manual_publishing_enabled"],
                request.google_account_available,
                request.google_account_available,
            ),
        )
        conn.execute(
            "UPDATE trend_collection_settings SET enabled=%s WHERE id=1",
            (after["trends_collection_enabled"],),
        )
        conn.execute(
            "UPDATE publication_mode_settings SET emergency_stopped=%s,blogger_api_restricted=CASE WHEN %s::boolean IS NULL THEN blogger_api_restricted ELSE NOT %s END,updated_at=clock_timestamp() WHERE scope_type='global' AND scope_key=''",
            (
                after["emergency_stop"],
                request.google_account_available,
                request.google_account_available,
            ),
        )
        saved = read(conn)
        changes = [
            {"key": key, "before": before[key], "after": saved[key]}
            for key in saved
            if key not in {"revision", "updated_at"} and before.get(key) != saved[key]
        ]
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('automation.controls.changed',%s)",
            (
                Jsonb(
                    {
                        "actor": request.actor,
                        "reason": request.reason,
                        "changes": changes,
                        "revision": saved["revision"],
                        "result": "persisted_worker_ack_pending",
                        "old_jobs_reauthorized": False,
                        "automatic_publication_approval_scope": approval_scope if operator_approval_changed else None,
                        "policy_checks_preserved": True,
                    },
                    dumps=lambda v: __import__("json").dumps(v, default=str),
                ),
            ),
        )
        if operator_approval_changed:
            from . import external_policy

            cost_policy_approved = external_policy._blogger_policy_approval() is not None
            public_write_approved = external_policy._blogger_public_publish_approval() is not None
            policy_checks = {
                "global_auto_publication_enabled": bool(saved["auto_publishing_enabled"]),
                "trends_route_enabled": bool(saved["trends_auto_publishing_enabled"]),
                "scheduled_route_enabled": bool(saved["scheduled_auto_publishing_enabled"]),
                "emergency_stop_clear": not bool(saved["emergency_stop"]),
                "blogger_api_restriction_clear": not bool(saved["blogger_api_restricted"]),
                "external_zero_cost_policy_approved": cost_policy_approved,
                "external_public_write_approved": public_write_approved,
                "legacy_operations_auto_approved": bool(saved["operations_auto_approved"]),
                "configured_mode": saved["configured_mode"],
                "blogger_write_mode": saved["blogger_write_mode"],
                "pending_auto_jobs_preserved": int(pending_auto_jobs["n"] if pending_auto_jobs else 0),
                "historical_jobs_reauthorized": False,
                "external_write_authorized_by_this_change": False,
            }
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES('automation.operator_publication_approval.changed',%s)",
                (
                    Jsonb(
                        {
                            "previous_approval": before["automatic_publication_operator_approved"],
                            "new_approval": saved["automatic_publication_operator_approved"],
                            "actor": request.actor.strip(),
                            "reason": request.reason.strip(),
                            "changed_at": saved["automatic_publication_approval_changed_at"],
                            "revision": saved["revision"],
                            "approved_scope": approval_scope,
                            "policy_checks": policy_checks,
                            "result": "persisted_worker_ack_pending",
                        },
                        dumps=lambda v: __import__("json").dumps(v, default=str),
                    ),
                ),
            )
    return {"saved": True, "revision": saved["revision"], "application": "pending_worker_ack"}


@router.post("/verify-google-readonly")
def verify_google() -> dict[str, Any]:
    from . import blogger_service
    from .google_http import GoogleFailure

    with connection() as conn:
        blogs = conn.execute(
            "SELECT id FROM blogger_blogs WHERE active AND oauth_connection_id IS NOT NULL ORDER BY id LIMIT 4"
        ).fetchall()
    results = []
    for blog in blogs:
        try:
            result = blogger_service.test_connection(blog["id"])
            results.append(
                {
                    "blog_id": str(blog["id"]),
                    "read_available": bool(result.get("tested")),
                    "write_verified": False,
                }
            )
        except GoogleFailure as exc:
            results.append(
                {
                    "blog_id": str(blog["id"]),
                    "read_available": False,
                    "reason": exc.category,
                    "http_status": exc.status,
                    "write_verified": False,
                }
            )
            if exc.status in {403, 429}:
                break
    with connection() as conn:
        payload = {
            "checked_at": datetime.now(UTC).isoformat(),
            "results": results,
            "write_verified": False,
        }
        conn.execute(
            "UPDATE automation_controls SET read_check_result=%s WHERE id=1", (Jsonb(payload),)
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('automation.google.read_checked',%s)",
            (Jsonb(payload),),
        )
    return payload


def grant_manual(conn: Any, job_id: Any, mode: str) -> None:
    state = read(conn)
    if not state["manual_publishing_enabled"]:
        raise HTTPException(409, "수동 발행이 비활성화되었습니다.")
    conn.execute(
        "INSERT INTO automation_publication_grants(job_id,epoch,lane,publication_mode) VALUES(%s,%s,'manual',%s)",
        (job_id, state["manual_epoch"], mode),
    )


def job_permitted(conn: Any, job_id: Any, *, running: bool = False) -> bool:
    state = read(conn)
    row = conn.execute(
        """SELECT j.status,j.blog_id,j.content_version_id,j.publication_mode AS job_publication_mode,g.* FROM automation_publication_grants g
        JOIN publishing_jobs j ON j.id=g.job_id JOIN content_versions v ON v.id=j.content_version_id
        WHERE g.job_id=%s AND NOT EXISTS(SELECT 1 FROM content_versions newer
         WHERE newer.group_id=v.group_id AND newer.localization_id IS NOT DISTINCT FROM v.localization_id
         AND newer.version>v.version)""",
        (job_id,),
    ).fetchone()
    if not row or (running and row["status"] != "running"):
        return False
    from .publication_discards import discarded

    if discarded(conn, row["content_version_id"], row["blog_id"]):
        return False
    if row["lane"] == "manual":
        return bool(
            state["manual_publishing_enabled"]
            and row["epoch"] == state["manual_epoch"]
            and not state["emergency_stop"]
            and not state["blogger_api_restricted"]
        )
    if not state["automatic_publication_operator_approved"]:
        return False
    from . import publication_origin

    origin = publication_origin.classify(conn, row["content_version_id"], row["blog_id"])
    candidate = dict(row)
    if row["job_publication_mode"] != row["publication_mode"]:
        return False
    if running:
        if row["lane"] == "auto" and origin.get("kind") == "google_trends":
            # Trends admission and the Blogger wire must share the same
            # fail-closed blocker decision. Editorial/SEO/research gaps are
            # retained as follow-ups by this policy; generic manual readiness
            # would turn those warnings into an extra approval gate here.
            from .trends_publication import validate_trends_job

            checked = validate_trends_job(conn, row["blog_id"], row["content_version_id"])
            candidate["quality_ready"] = bool(
                checked["row"] and checked["assessment"] and not checked["reasons"]
            )
        else:
            from .automation_auto import readiness

            _content, _snapshot, quality_reasons = readiness(
                conn, row["content_version_id"], row["blog_id"]
            )
            candidate["quality_ready"] = _content is not None and not quality_reasons
    candidate["duplicate"] = bool(
        conn.execute(
            """SELECT 1 FROM publishing_records p
        JOIN external_content_import_content_links l ON l.content_version_id=p.content_version_id
        WHERE p.blog_id=%s AND l.import_id=%s AND p.job_id<>%s AND p.remote_status IN ('LIVE','DRAFT') LIMIT 1""",
            (row["blog_id"], origin.get("import_id"), job_id),
        ).fetchone()
    )
    result = publication_origin.decide(
        state, origin, row["blog_id"], candidate, row["content_version_id"]
    )
    if not result["allowed"]:
        publication_origin.record_block(
            conn,
            row["content_version_id"],
            row["blog_id"],
            state["revision"],
            result,
            "job_admission",
        )
    return bool(result["allowed"])


@contextmanager
def write_guard(path: str | None = None, method: str = "POST") -> Iterator[None]:
    """OFF commits only after in-flight HTTP finishes; every later writer rechecks."""
    from .google_http import GoogleFailure

    try:
        with connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(20261102,103)")
            read(conn)
            from .publication_operation import blogger_writes_allowed

            if not blogger_writes_allowed():
                raise GoogleFailure("authoring_only_blogger_writes_suspended")
            from .automation_auto import AUTO_JOB
            from .external_policy import _manual_publication_approval

            approval = _manual_publication_approval.get()
            job_id = AUTO_JOB.get() or (approval[0] if approval else None)
            if AUTO_JOB.get() and method != "POST":
                raise GoogleFailure("automatic_update_not_authorized")
            if job_id and path:
                target = conn.execute(
                    "SELECT b.blog_id FROM publishing_jobs j JOIN blogger_blogs b ON b.id=j.blog_id WHERE j.id=%s",
                    (job_id,),
                ).fetchone()
                if not target or not path.startswith("/blogs/" + str(target["blog_id"]) + "/"):
                    raise GoogleFailure("publication_job_target_mismatch")
            yield
    except GoogleFailure:
        raise
    except (psycopg.Error, OSError, RuntimeError):
        raise GoogleFailure("automation_policy_unavailable") from None
