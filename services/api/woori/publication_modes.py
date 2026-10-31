"""Mode preferences and fail-closed eligibility for the publication pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Scope = Literal["global", "language", "blog"]
Mode = Literal["authoring_only", "manual", "auto"]


class ModeSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope_type: Scope = "global"
    scope_key: str = Field(default="", max_length=100)
    configured_mode: Mode = "manual"
    daily_auto_limit: int = Field(default=1, ge=0, le=3)
    minimum_interval_minutes: int = Field(default=1440, ge=60, le=10080)
    allowed_start_hour: int = Field(default=9, ge=0, le=23)
    allowed_end_hour: int = Field(default=17, ge=0, le=23)
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)
    allowed_categories: list[str] = Field(default_factory=list, max_length=30)
    excluded_topics: list[str] = Field(default_factory=list, max_length=100)
    max_source_age_hours: int = Field(default=24, ge=1, le=720)
    retry_limit: int = Field(default=0, ge=0, le=2)

    @field_validator("scope_key")
    @classmethod
    def normalize_scope_key(cls, value: str) -> str:
        return value.strip()

    @field_validator("allowed_categories", "excluded_topics")
    @classmethod
    def validate_entries(cls, values: list[str]) -> list[str]:
        normalized = [entry.strip() for entry in values]
        if any(not entry or len(entry) > 120 for entry in normalized):
            raise ValueError("settings entries must be non-empty and at most 120 characters")
        if len({entry.casefold() for entry in normalized}) != len(normalized):
            raise ValueError("settings entries must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_scope(self) -> ModeSettingsInput:
        if self.scope_type == "global" and self.scope_key:
            raise ValueError("global_scope_key_must_be_empty")
        if self.scope_type != "global" and not self.scope_key:
            raise ValueError("scoped_setting_requires_scope_key")
        if self.allowed_start_hour == self.allowed_end_hour:
            raise ValueError("publication_window_must_not_be_empty")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid_schedule_timezone") from None
        if self.configured_mode == "auto" and not self.allowed_categories:
            # Auto preferences can be saved, but they must define an explicit allowlist.
            raise ValueError("auto_mode_requires_category_allowlist")
        return self


AUTO_REQUIRED_FLAGS = (
    # These are evidence assertions, not user-supplied import fields. Callers
    # must derive them from persisted, reviewed evidence and current checks.
    "machine_passed",
    "source_accessible",
    "source_body_verified",
    "key_facts_verified",
    "claim_evidence_semantically_verified",
    "independent_verification_satisfied",
    "source_rights_cleared",
    "language_quality_passed",
    "topic_relevance_passed",
    "seo_passed",
    "html_safe",
    "not_duplicate",
    "sources_current",
    "blog_mapping_valid",
    "not_evaluation_only",
)


def assess_auto_candidate(
    evidence: dict[str, Any],
    *,
    requested_mode: str,
    emergency_stopped: bool,
    settings: dict[str, Any] | None = None,
    daily_published_count: int | None = None,
    last_published_at: datetime | None = None,
    now: datetime | None = None,
    auto_policy_active: bool = False,
    live_writes_enabled: bool = False,
) -> dict[str, Any]:
    """Assess content independently from human review and runtime dispatch authorization.

    `auto_eligible` never records or implies a human review/approval. Dispatch
    remains fail-closed until the separately activated operating policy and
    real Blogger write path are both available.
    """
    reasons: list[str] = []
    content_reasons: list[str] = []
    for flag in AUTO_REQUIRED_FLAGS:
        if evidence.get(flag) is not True:
            content_reasons.append(f"{flag}_not_verified")
    policy = settings or {}
    category = evidence.get("category")
    allowed_categories = policy.get("allowed_categories") or []
    if not category or category not in allowed_categories:
        content_reasons.append("category_not_allowlisted")
    topic = str(evidence.get("topic") or "").casefold()
    if any(str(excluded).casefold() in topic for excluded in policy.get("excluded_topics", [])):
        content_reasons.append("topic_excluded")
    daily_limit = int(policy.get("daily_auto_limit", 1))
    if daily_published_count is None:
        content_reasons.append("daily_publication_usage_not_verified")
    elif daily_published_count >= daily_limit:
        content_reasons.append("daily_publication_limit_reached")
    if (
        last_published_at is None
        or last_published_at.tzinfo is None
        or last_published_at.utcoffset() is None
    ):
        content_reasons.append("minimum_interval_not_verified")
    else:
        elapsed = ((now or datetime.now(UTC)) - last_published_at.astimezone(UTC)).total_seconds() / 60
        if elapsed < int(policy.get("minimum_interval_minutes", 1440)):
            content_reasons.append("minimum_publication_interval_not_met")
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        content_reasons.append("publication_window_not_verified")
    else:
        try:
            local_hour = current.astimezone(ZoneInfo(str(policy.get("timezone", "Asia/Seoul")))).hour
            start_hour = int(policy.get("allowed_start_hour", 9))
            end_hour = int(policy.get("allowed_end_hour", 17))
            inside_window = (start_hour <= local_hour < end_hour) if start_hour < end_hour else (
                local_hour >= start_hour or local_hour < end_hour
            )
            if not inside_window:
                content_reasons.append("outside_publication_window")
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            content_reasons.append("publication_window_not_verified")
    auto_eligible = not content_reasons
    reasons.extend(content_reasons)
    if requested_mode != "auto":
        reasons.append("auto_mode_not_configured")
    if emergency_stopped:
        reasons.append("emergency_stop_enabled")
    if not auto_policy_active:
        reasons.append("auto_policy_not_activated")
    if not live_writes_enabled:
        reasons.append("live_blogger_writes_disabled")
    return {
        "eligible": auto_eligible,
        "auto_eligible": auto_eligible,
        "dispatchable": auto_eligible and requested_mode == "auto" and not emergency_stopped
            and auto_policy_active and live_writes_enabled,
        "reasons": list(dict.fromkeys(reasons)),
        "human_review_required": False,
        "human_approval_recorded": False,
        "simulation_only": True,
    }


def effective_mode(configured_mode: str, *, emergency_stopped: bool) -> str:
    if configured_mode == "authoring_only":
        return "authoring_only"
    if configured_mode == "manual":
        return "manual"
    return "auto_preview_blocked" if not emergency_stopped else "auto_stopped"


def resolve_mode(settings: list[dict[str, Any]], language_code: str, blog_id: str) -> dict[str, Any]:
    """Resolve blog > language > global; missing scopes always inherit Manual."""
    by_scope = {(row["scope_type"], str(row["scope_key"])): row for row in settings}
    global_setting = by_scope.get(("global", ""))
    if global_setting and global_setting["configured_mode"] == "authoring_only":
        return dict(global_setting)
    selected = (
        by_scope.get(("blog", blog_id))
        or by_scope.get(("language", language_code))
        or by_scope.get(("global", ""))
    )
    return dict(selected) if selected else {
        "scope_type": "global", "scope_key": "", "configured_mode": "authoring_only",
        "daily_auto_limit": 1, "minimum_interval_minutes": 1440,
        "allowed_start_hour": 9, "allowed_end_hour": 17, "timezone": "Asia/Seoul",
        "allowed_categories": [], "excluded_topics": [], "max_source_age_hours": 24,
        "retry_limit": 0,
    }
