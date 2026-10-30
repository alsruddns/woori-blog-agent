"""Strict, idempotent intake for externally authored manuscripts.

Imports are stored as untrusted review material. They are never converted to a
publishable manuscript and never call a generator, network source, or Blogger.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
    model_validator,
)

from .content_representatives import body_digest, dedupe_manuscript_rows, same_manuscript_content
from .db import connection
from .editorial_taxonomy import (
    EDITORIAL_CATEGORIES,
    ISSUE_LABELS,
    language_candidates,
    suggested_labels,
)
from .scheduled_occurrence import validate_occurrence_metadata
from .topics import OFFICIAL_SOURCE_HOSTS

router = APIRouter(prefix="/admin/research/content-imports")
CATEGORY_SLUGS = {item["slug"] for item in EDITORIAL_CATEGORIES}
LANGUAGES = {"ko", "en", "ja", "zh-CN"}
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
INTERNAL_MARKER = re.compile(
    r"\b(?:FACT-F\d+|generation_ready|publish_ready|Research Package)\b", re.IGNORECASE
)


class ImportSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    title: str = Field(min_length=3, max_length=300)
    organization: str = Field(min_length=2, max_length=200)
    url: HttpUrl
    published_at: datetime | None = None
    observed_at: datetime
    language_code: str = Field(min_length=2, max_length=35)
    source_type: Literal["government", "regulatory", "filing", "company", "academic", "statistical", "news", "other"]
    rights_status: Literal["public_domain", "open_license", "permission_confirmed", "quotation_review_required", "unknown"]
    rights_note: str = Field(min_length=5, max_length=1000)

    @field_validator("url")
    @classmethod
    def https_only(cls, value: HttpUrl) -> HttpUrl:
        parts = urlsplit(str(value))
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("source_url_must_be_credential_free_https")
        return value

    @field_validator("observed_at", "published_at")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("source_timestamp_requires_timezone")
        return value


class ImportClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    claim_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    claim: str = Field(min_length=8, max_length=1500)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    evidence_excerpt: str = Field(min_length=8, max_length=2000)
    verification_status: Literal["source_span_verified", "corroborated", "conflict", "unverified"]
    factual_state: Literal["proposed", "planned", "approved", "enacted", "paid", "unverified"]

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("claim_source_ids_must_be_unique")
        return values


class TargetAudience(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    language_code: str = Field(min_length=2, max_length=35)
    target_region: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    reader_relevance_reason: str = Field(min_length=10, max_length=1000)


class SeoMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    search_intent: str = Field(min_length=5, max_length=500)
    primary_terms: list[str] = Field(min_length=1, max_length=10)
    related_terms: list[str] = Field(default_factory=list, max_length=20)
    seo_title: str = Field(min_length=5, max_length=200)
    search_description: str = Field(min_length=30, max_length=500)
    core_question: str = Field(min_length=5, max_length=500)
    core_answer: str = Field(min_length=10, max_length=1000)


class ContentImport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["1.0"]
    content_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    event_group_id: str = Field(min_length=3, max_length=128)
    research_package_id: str | None = Field(default=None, max_length=128)
    parent_content_id: str | None = Field(default=None, max_length=128)
    relation: Literal["original", "localized", "revision"]
    source_region: str = Field(min_length=2, max_length=3, pattern=r"^(?:[A-Z]{2,3}|[0-9]{3})$")
    language_code: str = Field(min_length=2, max_length=35)
    target_audiences: list[TargetAudience] = Field(min_length=1, max_length=4)
    title: str = Field(min_length=5, max_length=200)
    body_markdown: str = Field(min_length=100, max_length=100000)
    category: str
    google_trends_based: bool
    source_ids: list[str] = Field(min_length=1, max_length=20)
    sources: list[ImportSource] = Field(min_length=1, max_length=20)
    claims: list[ImportClaim] = Field(min_length=1, max_length=80)
    fact_checked_at: datetime
    seo: SeoMetadata
    blogger_labels: list[str] = Field(default_factory=list, max_length=8)
    generation_method: Literal["manual_codex_import", "chatgpt_scheduled_export", "other_external_export", "codex_trends_export"]
    model_name: str | None = Field(default=None, max_length=100)
    generated_at: datetime
    created_by: str = Field(min_length=2, max_length=100)

    @field_validator("body_markdown")
    @classmethod
    def safe_markdown_only(cls, value: str) -> str:
        if HTML_TAG.search(value):
            raise ValueError("raw_html_is_not_allowed_in_import_markdown")
        if "\x00" in value:
            raise ValueError("control_character_not_allowed")
        if INTERNAL_MARKER.search(value):
            raise ValueError("internal_workflow_marker_not_allowed_in_reader_content")
        return value

    @field_validator("fact_checked_at", "generated_at")
    @classmethod
    def top_level_timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("import_timestamp_requires_timezone")
        return value

    @model_validator(mode="after")
    def evidence_and_metadata_consistent(self) -> ContentImport:
        if self.category not in CATEGORY_SLUGS:
            raise ValueError("category_not_in_editorial_taxonomy")
        if self.language_code not in LANGUAGES:
            raise ValueError("unsupported_language")
        if self.relation == "original" and self.parent_content_id is not None:
            raise ValueError("original_content_cannot_have_parent")
        if self.relation != "original" and not self.parent_content_id:
            raise ValueError("derived_content_requires_parent")
        audience_languages = [target.language_code for target in self.target_audiences]
        if len(set(self.source_ids)) != len(self.source_ids) or len(set(audience_languages)) != len(audience_languages):
            raise ValueError("duplicate_import_reference")
        source_ids = {source.source_id for source in self.sources}
        if source_ids != set(self.source_ids):
            raise ValueError("source_id_manifest_mismatch")
        for claim in self.claims:
            if not set(claim.source_ids).issubset(source_ids):
                raise ValueError("claim_references_unknown_source")
        if self.language_code not in {target.language_code for target in self.target_audiences}:
            raise ValueError("manuscript_language_must_be_an_explicit_target_audience")
        labels = suggested_labels(self.category, self.language_code, google_trends_based=self.google_trends_based)
        if self.google_trends_based and ISSUE_LABELS[self.language_code] not in self.blogger_labels:
            raise ValueError("google_trends_locale_issue_label_required")
        if any(label not in labels for label in self.blogger_labels):
            raise ValueError("unrecognized_or_unreviewed_blogger_label")
        return self


class ImportSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    submitted_by: str = Field(min_length=2, max_length=100)
    item: ContentImport
    manual_automation_origin: ManualAutomationOrigin | None = None

    @model_validator(mode="after")
    def manual_origin_matches_item(self) -> ImportSubmission:
        if self.manual_automation_origin and self.item.generation_method != "manual_codex_import":
            raise ValueError("manual_automation_origin_requires_manual_codex_import")
        return self


class ManualAutomationOrigin(BaseModel):
    """Untrusted, locally observed provenance for an explicit Desktop Run now."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    execution_mode: Literal["manual"]
    automation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    manual_run_id: str = Field(min_length=20, max_length=180,
                               pattern=r"^codex-manual:[A-Za-z0-9_.:-]+:[0-9a-f-]{36}$")
    session_id: UUID
    turn_trigger: Literal["automation_cron_run_now"]
    invoked_at: datetime
    recovery_of_session_id: UUID | None = None
    recovery_of_turn_id: UUID | None = None
    recovery_of_scheduled_slot: datetime | None = None
    recovery_reason_code: Literal["usage_limit_exceeded"] | None = None
    inbox_file_name: str | None = Field(default=None, min_length=1, max_length=180,
                                        pattern=r"^[A-Za-z0-9_.-]+$")
    inbox_file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("invoked_at", "recovery_of_scheduled_slot")
    @classmethod
    def manual_timestamp_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("manual_automation_timestamp_requires_timezone")
        return value

    @model_validator(mode="after")
    def recovery_fields_are_complete(self) -> ManualAutomationOrigin:
        recovery = (self.recovery_of_session_id, self.recovery_of_turn_id,
                    self.recovery_of_scheduled_slot, self.recovery_reason_code)
        if any(value is not None for value in recovery) and any(value is None for value in recovery):
            raise ValueError("manual_recovery_link_must_be_complete")
        if not self.manual_run_id.startswith(f"codex-manual:{self.automation_id}:"):
            raise ValueError("manual_run_id_automation_mismatch")
        return self


class ScheduledImportOrigin(BaseModel):
    """Untrusted provenance asserted by a locally produced scheduled export."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task_type: Literal[
        "market_close_kr", "market_close_jp", "market_close_cn", "market_close_us",
        "weekly_finance", "trends_major_issue", "scheduled_article",
    ]
    task_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    occurrence_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    occurrence_id_source: Literal["scheduler_issued", "project_derived_kst_slot"] | None = None
    scheduler_occurrence_id: str | None = Field(default=None, min_length=8, max_length=160,
                                                 pattern=r"^[A-Za-z0-9_.:-]+$")
    automation_id: str | None = Field(default=None, min_length=1, max_length=128,
                                       pattern=r"^[A-Za-z0-9_.:-]+$")
    scheduled_slot: datetime | None = None
    local_duplicate_status: Literal[
        "already_published", "already_imported", "failed_only", "not_found", "unknown"
    ] | None = None
    remote_duplicate_status: Literal[
        "not_checked", "clear", "found", "unknown", "database_verified"
    ] | None = None
    remote_failure_code: str | None = Field(default=None, min_length=1, max_length=120)
    draft_import_allowed: bool | None = None
    publication_recheck_required: bool | None = None
    publication_retry_status: Literal[
        "not_started", "not_required", "required_before_publication", "pending"
    ] | None = None
    executed_at: datetime
    market_date: date | None = None
    target_language_code: str = Field(min_length=2, max_length=35)
    target_blog_id: str = Field(min_length=5, max_length=32, pattern=r"^[0-9]+$")
    target_blog_url: HttpUrl
    source_as_of: datetime
    inbox_file_name: str | None = Field(default=None, min_length=1, max_length=180, pattern=r"^[A-Za-z0-9_.-]+$")
    inbox_file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("executed_at", "source_as_of")
    @classmethod
    def scheduled_timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_timestamp_requires_timezone")
        return value

    @field_validator("target_blog_url")
    @classmethod
    def blogger_url_is_canonical_https(cls, value: HttpUrl) -> HttpUrl:
        parts = urlsplit(str(value))
        if (
            parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment or parts.port
        ):
            raise ValueError("scheduled_target_must_be_canonical_blogspot_url")
        if not parts.hostname.endswith(".blogspot.com"):
            raise ValueError("scheduled_target_must_be_registered_blogspot_url")
        return value

    @model_validator(mode="after")
    def market_occurrence_has_session_date(self) -> ScheduledImportOrigin:
        if self.task_type.startswith("market_close_") and self.market_date is None:
            raise ValueError("market_close_requires_market_date")
        if self.source_as_of > self.executed_at:
            raise ValueError("source_as_of_cannot_follow_scheduled_execution")
        validate_occurrence_metadata(
            occurrence_id=self.occurrence_id,
            occurrence_id_source=self.occurrence_id_source,
            scheduler_occurrence_id=self.scheduler_occurrence_id,
            automation_id=self.automation_id,
            scheduled_slot=self.scheduled_slot,
        )
        duplicate_fields = (
            self.local_duplicate_status, self.remote_duplicate_status,
            self.draft_import_allowed, self.publication_recheck_required,
            self.publication_retry_status,
        )
        if any(value is not None for value in duplicate_fields) and any(
            value is None for value in duplicate_fields
        ):
            raise ValueError("duplicate_preflight_metadata_must_be_complete")
        if self.draft_import_allowed is True and self.local_duplicate_status not in {
            "not_found", "failed_only"
        }:
            raise ValueError("draft_import_requires_locally_clear_duplicate_status")
        if self.remote_duplicate_status in {"not_checked", "unknown"}:
            if self.publication_recheck_required is not True:
                raise ValueError("remote_unconfirmed_requires_publication_recheck")
            expected_retry = (
                "pending" if self.remote_duplicate_status == "unknown"
                else "required_before_publication"
            )
            if self.publication_retry_status != expected_retry:
                raise ValueError("remote_unconfirmed_retry_state_mismatch")
        if self.remote_duplicate_status == "found" and self.draft_import_allowed is True:
            raise ValueError("remote_duplicate_found_cannot_allow_new_draft")
        return self


class ScheduledImportEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["woori-scheduled-content-import/1.0"]
    submitted_by: str = Field(min_length=2, max_length=100)
    item: ContentImport
    scheduled_origin: ScheduledImportOrigin

    @model_validator(mode="after")
    def schedule_and_manuscript_agree(self) -> ScheduledImportEnvelope:
        if self.item.generation_method != "chatgpt_scheduled_export":
            raise ValueError("scheduled_envelope_requires_scheduled_export_method")
        if self.item.language_code != self.scheduled_origin.target_language_code:
            raise ValueError("scheduled_target_language_mismatch")
        required_language = {
            "market_close_kr": "ko",
            "market_close_jp": "ja",
            "market_close_cn": "zh-CN",
            "market_close_us": "en",
        }.get(self.scheduled_origin.task_type)
        if required_language and self.item.language_code != required_language:
            raise ValueError("market_task_language_mismatch")
        trends_origin = self.scheduled_origin.task_type == "trends_major_issue"
        if trends_origin != self.item.google_trends_based:
            raise ValueError("trends_task_type_must_match_actual_trends_origin")
        return self


class ManualAutomationImportEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["woori-manual-automation-content-import/1.0"]
    submitted_by: str = Field(min_length=2, max_length=100)
    item: ContentImport
    manual_origin: ManualAutomationOrigin

    @model_validator(mode="after")
    def manual_envelope_is_not_scheduled(self) -> ManualAutomationImportEnvelope:
        if self.item.generation_method != "manual_codex_import":
            raise ValueError("manual_automation_envelope_requires_manual_codex_import")
        return self


class DuplicateCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    language_code: Literal["ko", "en", "ja", "zh-CN"]
    target_country: str = Field(min_length=2, max_length=3, pattern=r"^(?:[A-Z]{2,3}|[0-9]{3})$")
    target_blog_id: str = Field(min_length=5, max_length=32, pattern=r"^[0-9]+$")
    trade_date: date | None = None
    event_group_id: str = Field(min_length=3, max_length=128)
    topic: str = Field(min_length=3, max_length=300)
    content_id: str | None = Field(default=None, min_length=8, max_length=128)
    stage: Literal["generation", "publication"] = "publication"


@router.post("/duplicate-check")
def scheduled_duplicate_check(request: DuplicateCheckRequest) -> dict[str, Any]:
    """Read-only idempotency preflight for Scheduled tasks; uncertainty never means absent."""
    def finish(result: dict[str, Any]) -> dict[str, Any]:
        with connection() as audit_conn:
            audit_conn.execute(
                """INSERT INTO audit_events(event_type,language_code,payload)
                VALUES ('content_import.scheduled_duplicate_check',%s,%s)""",
                (request.language_code, Jsonb({
                    "event_group_id": request.event_group_id,
                    "content_id": request.content_id,
                    "stage": request.stage,
                    "target_country": request.target_country,
                    "target_blog_id": request.target_blog_id,
                    "trade_date": request.trade_date.isoformat() if request.trade_date else None,
                    "status": result.get("status"), "reason": result.get("reason"),
                    "db_import_match": result.get("db_import_match"),
                    "blogger_read_complete": result.get("blogger_read_complete"),
                    "local_duplicate_status": result.get("local_status"),
                    "remote_duplicate_status": result.get("remote_status"),
                    "remote_failure_code": result.get("remote_failure_code"),
                    "draft_import_allowed": result.get("draft_import_allowed", False),
                    "publication_recheck_required": result.get("publication_recheck_required", True),
                    "publication_retry_status": result.get("publication_retry_status", "not_started"),
                    "read_only_preflight": True,
                })),
            )
        return result

    with connection() as conn:
        blog = conn.execute(
            """SELECT id,blog_id,language_code,url,active,connection_verified_at,
            oauth_connection_id FROM blogger_blogs WHERE blog_id=%s AND language_code=%s""",
            (request.target_blog_id, request.language_code),
        ).fetchone()
        if not blog:
            return finish({"status": "unknown", "reason": "target_blog_not_registered",
                           "local_status": "unknown", "remote_status": "not_checked",
                           "remote_failure_code": None, "draft_import_allowed": False,
                           "publication_recheck_required": True,
                           "publication_retry_status": "not_started",
                           "db_import_match": False, "blogger_read_complete": False})
        if not blog["active"]:
            return finish({"status": "unknown", "reason": "target_blog_inactive",
                           "local_status": "unknown", "remote_status": "not_checked",
                           "remote_failure_code": None, "draft_import_allowed": False,
                           "publication_recheck_required": True,
                           "publication_retry_status": "not_started",
                           "db_import_match": False, "blogger_read_complete": False})
        imported = conn.execute(
            """SELECT i.id,i.external_content_id,i.event_group_id,i.source_region,i.language_code,
            i.title,i.state,i.received_at,v.id AS import_version_id,link.content_version_id,
            r.remote_post_id,r.remote_url,r.remote_status,r.remote_verified_at
            FROM external_content_imports i
            LEFT JOIN external_content_import_versions v ON v.import_id=i.id
            LEFT JOIN external_content_import_content_links link ON link.import_id=i.id
              AND link.import_version_id=v.id
            LEFT JOIN publishing_records r ON r.blog_id=%s AND r.content_version_id=link.content_version_id
            WHERE i.language_code=%s AND i.source_region=%s AND
              (i.event_group_id=%s OR lower(i.title)=lower(%s) OR i.external_content_id=%s
               OR (%s::date IS NOT NULL AND EXISTS (SELECT 1 FROM audit_events a
                 WHERE a.event_type='content.import.scheduled_origin_recorded'
                   AND a.payload->>'import_id'=i.id::text AND a.payload->>'market_date'=%s)))
            ORDER BY i.received_at DESC,i.id DESC LIMIT 20""",
            (blog["id"], request.language_code, request.target_country,
             request.event_group_id, request.topic, request.content_id or "",
             request.trade_date, request.trade_date.isoformat() if request.trade_date else ""),
        ).fetchall()
        if imported:
            published = next((row for row in imported if row["remote_status"] == "LIVE"
                              and row["remote_verified_at"]), None)
            if published:
                return finish({"status": "already_published", "reason": "verified_database_publication_record",
                        "local_status": "already_published", "remote_status": "database_verified",
                        "remote_failure_code": None, "draft_import_allowed": False,
                        "publication_recheck_required": False, "publication_retry_status": "not_required",
                        "import_id": str(published["id"]), "content_version_id": str(published["content_version_id"]),
                        "post_id": published["remote_post_id"], "url": published["remote_url"],
                        "blogger_read_complete": False})
            if request.stage == "generation":
                return finish({"status": "already_imported", "reason": "matching_import_exists_without_verified_publication",
                        "local_status": "already_imported", "remote_status": "not_checked",
                        "remote_failure_code": None, "draft_import_allowed": False,
                        "publication_recheck_required": True, "publication_retry_status": "required_before_publication",
                        "import_id": str(imported[0]["id"]),
                        "content_version_id": str(imported[0]["content_version_id"]) if imported[0]["content_version_id"] else None,
                        "blogger_read_complete": False, "db_import_match": True})
            from .scheduled_duplicates import find_remote_duplicate
            remote = find_remote_duplicate(UUID(str(blog["id"])), request.topic)
            if remote["status"] == "found":
                return finish({"status": "already_published", "reason": "remote_live_title_match",
                        "local_status": "already_imported", "remote_status": "found",
                        "remote_failure_code": None, "draft_import_allowed": False,
                        "publication_recheck_required": False, "publication_retry_status": "not_required",
                        "import_id": str(imported[0]["id"]), "post_id": remote.get("post_id"),
                        "url": remote.get("url"), "blogger_read_complete": True})
            return finish({"status": "already_imported", "reason": "matching_import_exists_without_verified_publication",
                    "local_status": "already_imported", "remote_status": remote["status"],
                    "remote_failure_code": remote.get("reason") if remote["status"] == "unknown" else None,
                    "draft_import_allowed": False, "publication_recheck_required": True,
                    "publication_retry_status": "pending" if remote["status"] == "unknown" else "required_before_publication",
                    "import_id": str(imported[0]["id"]),
                    "content_version_id": str(imported[0]["content_version_id"]) if imported[0]["content_version_id"] else None,
                    "blogger_read_complete": remote["status"] != "unknown",
                    "blogger_read_status": remote["status"],
                    "remote_read_reason": remote.get("reason")})
        failed_ids: list[str] = []
        pending_ids: list[str] = []
        local_root = Path(__file__).resolve().parents[3] / ".local" / "gpt-scheduled-import"
        if local_root.exists():
            try:
                if local_root.is_symlink() or local_root.resolve(strict=True).parent != local_root.parent.resolve(strict=True):
                    raise OSError("unsafe_inbox_root")
                for folder in ("incoming", "ready", "processing", "completed", "quarantine", "rejected"):
                    directory = local_root / folder
                    if not directory.exists():
                        continue
                    if directory.is_symlink() or directory.resolve(strict=True).parent != local_root.resolve(strict=True):
                        raise OSError("unsafe_inbox_state_directory")
                    for path in directory.glob("*.json"):
                        if path.is_symlink() or path.stat().st_size > 1_048_576:
                            continue
                        try:
                            envelope = json.loads(path.read_text(encoding="utf-8"))
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            continue
                        item = envelope.get("item", envelope) if isinstance(envelope, dict) else {}
                        if not isinstance(item, dict):
                            continue
                        if (item.get("event_group_id") == request.event_group_id
                                or (request.content_id and item.get("content_id") == request.content_id)):
                            file_id = str(item.get("content_id") or "unknown")
                            if folder in {"quarantine", "rejected"}:
                                failed_ids.append(file_id)
                            else:
                                pending_ids.append(file_id)
            except OSError:
                return finish({"status": "unknown", "reason": "local_failure_history_unavailable",
                               "local_status": "unknown", "remote_status": "not_checked",
                               "remote_failure_code": "local_failure_history_unavailable",
                               "draft_import_allowed": False, "publication_recheck_required": True,
                               "publication_retry_status": "not_started",
                               "db_import_match": False, "blogger_read_complete": False})
        if pending_ids:
            return finish({"status": "unknown", "reason": "matching_file_pending_or_completed_without_database_import",
                    "local_status": "unknown", "remote_status": "not_checked",
                    "remote_failure_code": None, "draft_import_allowed": False,
                    "publication_recheck_required": True, "publication_retry_status": "not_started",
                    "pending_content_ids": sorted(set(pending_ids)),
                    "db_import_match": False, "blogger_read_complete": False})
        local_status = "failed_only" if failed_ids else "not_found"
        if request.stage == "generation":
            return finish({"status": "unknown", "reason": "remote_duplicate_check_deferred",
                    "local_status": local_status, "remote_status": "not_checked",
                    "remote_failure_code": None, "draft_import_allowed": True,
                    "publication_recheck_required": True,
                    "publication_retry_status": "required_before_publication",
                    "failed_content_ids": sorted(set(failed_ids)),
                    "safe_to_create_new_original_id": local_status in {"failed_only", "not_found"},
                    "preserve_failed_files": True, "db_import_match": False,
                    "blogger_read_complete": False})
        if not blog["connection_verified_at"] or not blog["oauth_connection_id"]:
            return finish({"status": "unknown", "reason": "blogger_read_connection_unverified",
                    "local_status": local_status, "remote_status": "unknown",
                    "remote_failure_code": "blogger_read_connection_unverified",
                    "draft_import_allowed": False, "publication_recheck_required": True,
                    "publication_retry_status": "pending",
                    "failed_content_ids": sorted(set(failed_ids)),
                    "preserve_failed_files": True,
                    "db_import_match": False, "blogger_read_complete": False})
    from .scheduled_duplicates import find_remote_duplicate
    remote = find_remote_duplicate(UUID(str(blog["id"])), request.topic)
    if remote["status"] == "found":
        return finish({"status": "already_published", "reason": remote["reason"],
                "local_status": local_status, "remote_status": "found", "remote_failure_code": None,
                "draft_import_allowed": False, "publication_recheck_required": False,
                "publication_retry_status": "not_required",
                "post_id": remote.get("post_id"), "url": remote.get("url"),
                "blogger_read_complete": True})
    if remote["status"] == "unknown":
        return finish({"status": "unknown", "reason": remote["reason"],
                       "local_status": local_status, "remote_status": "unknown",
                       "remote_failure_code": remote.get("reason"), "draft_import_allowed": False,
                       "publication_recheck_required": True, "publication_retry_status": "pending",
                       "http_status": remote.get("http_status"),
                       "scanned_posts": remote.get("scanned_posts"),
                       "preserve_failed_files": True,
                       "db_import_match": False, "blogger_read_complete": False})
    if failed_ids:
        return finish({"status": "failed_only", "reason": "matching_quarantined_or_rejected_file_without_database_import_or_remote_post",
                "local_status": "failed_only", "remote_status": "clear", "remote_failure_code": None,
                "draft_import_allowed": True, "publication_recheck_required": True,
                "publication_retry_status": "required_before_publication",
                "failed_content_ids": sorted(set(failed_ids)), "safe_to_create_new_original_id": True,
                "preserve_failed_files": True, "blogger_read_complete": True})
    return finish({"status": "not_found", "reason": "database_and_complete_blogger_read_contain_no_match",
                   "local_status": "not_found", "remote_status": "clear", "remote_failure_code": None,
                   "draft_import_allowed": True, "publication_recheck_required": True,
                   "publication_retry_status": "required_before_publication",
                   "db_import_match": False, "blogger_read_complete": True})


class ImportVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    base_version_id: UUID
    title: str = Field(min_length=5, max_length=200)
    body_markdown: str = Field(min_length=100, max_length=100000)
    seo_metadata: SeoMetadata
    blogger_labels: list[str] = Field(max_length=8)
    author_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("body_markdown")
    @classmethod
    def safe_version_markdown(cls, value: str) -> str:
        return ContentImport.safe_markdown_only(value)


class ImportAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID | None = None


class ImportReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version_id: UUID
    disposition: Literal["review_started", "changes_requested", "editorial_review_passed"]
    reviewer_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=5, max_length=2000)
    sources_examined: bool = False
    claims_checked: bool = False
    rights_reviewed: bool = False


class LocalizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_language: Literal["ko", "en", "ja", "zh-CN"]
    requester_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=5, max_length=1000)


class LocalizationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requester_label: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=5, max_length=1000)


class MockPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version_id: UUID
    idempotency_key: str = Field(min_length=12, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    scenario: Literal["success", "timeout", "auth_failure", "server_failure", "uncertain"] = "success"
    requested_by: str = Field(min_length=2, max_length=120)


def _version_digest(title: str, body: str, seo: dict[str, Any], labels: list[str]) -> str:
    import json
    canonical = json.dumps(
        {"title": title, "body": body, "seo": seo, "labels": labels},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _latest_version(conn: Any, import_id: UUID) -> Any:
    row = conn.execute(
        "SELECT * FROM external_content_import_versions WHERE import_id=%s ORDER BY version_number DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(409, "Import review migration 047 is required")
    return row


def _require_import(conn: Any, import_id: UUID) -> Any:
    row = conn.execute("SELECT * FROM external_content_imports WHERE id=%s", (import_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Imported manuscript not found")
    return row


def _audit(conn: Any, event_type: str, payload: dict[str, Any]) -> None:
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)", (event_type, Jsonb(payload)))


def _link_manuscript_version(
    conn: Any, import_id: UUID, imported: Any, import_version_id: UUID,
    title: str, body: str, parent_content_version_id: UUID | None = None,
) -> UUID:
    group = conn.execute(
        "SELECT content_group_id FROM external_content_import_groups WHERE event_group_id=%s",
        (imported["event_group_id"],),
    ).fetchone()
    if group:
        group_id = group["content_group_id"]
    elif imported["relation"] == "original":
        group_id = conn.execute("INSERT INTO content_groups DEFAULT VALUES RETURNING id").fetchone()["id"]
        conn.execute("INSERT INTO external_content_import_groups(event_group_id,content_group_id) VALUES (%s,%s)",
            (imported["event_group_id"], group_id))
    else:
        raise HTTPException(409, "The parent manuscript event group has no manuscript mapping")

    audiences = imported["target_audiences"]
    target_region = next((item.get("target_region") for item in audiences
        if item.get("language_code") == imported["language_code"] and item.get("target_region")), "")
    conn.execute(
        "INSERT INTO content_localizations(group_id,language_code,target_country) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
        (group_id, imported["language_code"], target_region),
    )
    localization = conn.execute(
        "SELECT id FROM content_localizations WHERE group_id=%s AND language_code=%s AND target_country=%s",
        (group_id, imported["language_code"], target_region),
    ).fetchone()
    if not localization:
        raise HTTPException(409, "Manuscript localization could not be mapped")
    localization_id = localization["id"]
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(localization_id),))
    next_version = int(conn.execute(
        "SELECT COALESCE(MAX(version),0)+1 AS next_version FROM content_versions WHERE localization_id=%s",
        (localization_id,),
    ).fetchone()["next_version"])
    content_version = conn.execute(
        """INSERT INTO content_versions(group_id,language,localization_id,version,title,body,source_version_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (group_id, imported["language_code"], localization_id, next_version, title, body,
         parent_content_version_id),
    ).fetchone()
    if not content_version:
        raise HTTPException(503, "Manuscript version mapping could not be stored")
    content_version_id = content_version["id"]
    conn.execute(
        "INSERT INTO external_content_import_content_links(import_id,import_version_id,content_version_id) VALUES (%s,%s,%s)",
        (import_id, import_version_id, content_version_id),
    )
    return cast(UUID, content_version_id)


def _require_import_review_schema(conn: Any) -> None:
    # The runtime role intentionally cannot read schema_migrations. Migration 048
    # creates this bridge relation and grants the application role its required
    # privileges, so check the required capability without expanding DB grants.
    relation = conn.execute(
        "SELECT to_regclass('public.external_content_import_content_links') AS table_name"
    ).fetchone()
    if not relation or not relation.get("table_name"):
        raise HTTPException(409, "Content import manuscript bridge migration 048 is required")


@router.get("")
def list_content_imports(
    limit: int | None = Query(default=None, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    q: str = Query(default="", max_length=200),
    origin: str = Query(default="all", max_length=40),
) -> dict[str, Any]:
    with connection() as conn:
        _require_import_review_schema(conn)
        rows = conn.execute(
            """WITH RECURSIVE import_lineage AS (
              SELECT id,external_content_id,parent_content_id,external_content_id AS root_content_id
              FROM external_content_imports WHERE parent_content_id IS NULL
              UNION ALL
              SELECT child.id,child.external_content_id,child.parent_content_id,parent.root_content_id
              FROM external_content_imports child JOIN import_lineage parent
                ON child.parent_content_id=parent.external_content_id
            ), latest_imports AS (
              SELECT i.id,i.external_content_id,i.event_group_id,i.language_code,i.source_region,i.category,
                i.title,i.content_sha256,i.state,i.received_at,i.generation_method,i.model_name,
                NULL::boolean AS google_trends_based,i.parent_content_id,lineage.root_content_id,
                mapped.import_version_id,mapped.content_version_id,cv.group_id,cv.localization_id,
                cv.version AS content_version_number,cv.created_at AS content_version_created_at,
                latest.body_markdown,
                COALESCE(review.event_type,'awaiting_human_review') AS editorial_review_status,
                COALESCE(assessment.machine_passed,false) AS machine_passed,
                COALESCE(scheduled.target_blog_id,sole_blog.blog_id::text) AS target_blog_id,
                COALESCE(cv.group_id::text,lineage.root_content_id,i.external_content_id) AS representative_group,
                failure.event_type AS auto_failure_event_type,failure.payload AS auto_failure_payload
              FROM external_content_imports i
              LEFT JOIN import_lineage lineage ON lineage.id=i.id
              LEFT JOIN LATERAL (
                SELECT v.id AS import_version_id,l.content_version_id FROM external_content_import_versions v
                LEFT JOIN external_content_import_content_links l ON l.import_id=v.import_id AND l.import_version_id=v.id
                WHERE v.import_id=i.id ORDER BY v.version_number DESC,v.created_at DESC,v.id DESC LIMIT 1
              ) mapped ON true
              LEFT JOIN content_versions cv ON cv.id=mapped.content_version_id
              LEFT JOIN LATERAL (
                SELECT event_type FROM external_content_import_review_events
                WHERE import_id=i.id AND version_id=mapped.import_version_id
                ORDER BY created_at DESC,id DESC LIMIT 1
              ) review ON true
              LEFT JOIN LATERAL (
                SELECT machine_passed FROM external_content_import_assessments
                WHERE import_id=i.id AND version_id=mapped.import_version_id
                ORDER BY assessed_at DESC,id DESC LIMIT 1
              ) assessment ON true
              LEFT JOIN LATERAL (
                SELECT v.body_markdown FROM external_content_import_versions v
                WHERE v.import_id=i.id ORDER BY v.version_number DESC,v.created_at DESC,v.id DESC LIMIT 1
              ) latest ON true
              LEFT JOIN LATERAL (
                SELECT payload->>'target_blog_id' AS target_blog_id
                FROM audit_events WHERE event_type='content.import.scheduled_origin_recorded'
                  AND payload->>'import_id'=i.id::text
                ORDER BY created_at DESC,id DESC LIMIT 1
              ) scheduled ON true
              LEFT JOIN LATERAL (
                SELECT CASE WHEN count(*)=1 THEN min(blog_id) END AS blog_id
                FROM blogger_blogs WHERE active AND language_code=i.language_code
              ) sole_blog ON true
              LEFT JOIN LATERAL (
                SELECT event_type,payload FROM audit_events
                WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
                  AND payload->>'import_id'=i.id::text
                ORDER BY id DESC LIMIT 1
              ) failure ON true
            ), ranked AS (
              SELECT latest_imports.*,row_number() OVER (
                PARTITION BY COALESCE(group_id::text,root_content_id,external_content_id),language_code,
                  COALESCE(localization_id::text,language_code)
                ORDER BY content_version_number DESC NULLS LAST,content_version_created_at DESC NULLS LAST,
                  received_at DESC,id DESC
              ) AS representative_rank
              FROM latest_imports
            )
            SELECT id,external_content_id,event_group_id,language_code,source_region,category,title,
              content_sha256,state,received_at,generation_method,model_name,google_trends_based,
              content_version_id,content_version_number,import_version_id,editorial_review_status,machine_passed,
              body_markdown,target_blog_id,representative_group,auto_failure_event_type,auto_failure_payload
            FROM ranked WHERE representative_rank=1
            ORDER BY received_at DESC,id DESC"""
        ).fetchall()
        candidates = [dict(row) for row in rows]
        representatives, duplicate_count = dedupe_manuscript_rows(candidates)
        for candidate in representatives:
            candidate.pop("body_markdown", None)
            candidate.pop("representative_group", None)
            candidate["auto_publication_failure"] = candidate.get("auto_failure_event_type") == "publication.auto_failure.recorded"
            candidate["auto_failure"] = candidate.pop("auto_failure_payload", None) if candidate["auto_publication_failure"] else None
            candidate.pop("auto_failure_event_type", None)
        query = q.strip().casefold()
        if query:
            representatives = [row for row in representatives if query in " ".join(
                str(row.get(key) or "") for key in (
                    "title", "external_content_id", "event_group_id", "source_region", "language_code",
                )
            ).casefold()]
        if origin == "trends":
            representatives = [row for row in representatives if row.get("google_trends_based") is True]
        elif origin not in {"all", "other_external_export"}:
            representatives = [row for row in representatives if row.get("generation_method") == origin]
        elif origin == "other_external_export":
            representatives = [row for row in representatives if row.get("google_trends_based") is not True
                               and row.get("generation_method") not in {"chatgpt_scheduled_export", "manual_codex_import"}]
        total_count = len(representatives)
        effective_page_size = limit if limit is not None else page_size
        page_count = (total_count + effective_page_size - 1) // effective_page_size
        start = (page - 1) * effective_page_size
        return {"items": representatives[start:start + effective_page_size],
            "total_count": total_count, "page": page, "page_size": effective_page_size,
            "page_count": page_count, "duplicates_suppressed": duplicate_count,
            "categories": [dict(row) for row in EDITORIAL_CATEGORIES],
            "generator_available": False, "publication_enabled": False, "requires_human_review": True}


@router.get("/{import_id}")
def get_content_import(import_id: UUID) -> dict[str, Any]:
    with connection() as conn:
        _require_import_review_schema(conn)
        row = _require_import(conn, import_id)
        latest = conn.execute(
            """SELECT v.*,l.content_version_id FROM external_content_import_versions v
            LEFT JOIN external_content_import_content_links l ON l.import_id=v.import_id AND l.import_version_id=v.id
            WHERE v.import_id=%s ORDER BY v.version_number DESC LIMIT 1""",
            (import_id,),
        ).fetchone()
        versions = conn.execute(
            """SELECT v.id,v.version_number,v.parent_version_id,v.title,v.content_sha256,v.author_label,
                v.change_reason,v.created_at,l.content_version_id
            FROM external_content_import_versions v LEFT JOIN external_content_import_content_links l
              ON l.import_id=v.import_id AND l.import_version_id=v.id
            WHERE v.import_id=%s ORDER BY v.version_number DESC""",
            (import_id,),
        ).fetchall()
        lineage_history = conn.execute(
            """WITH RECURSIVE import_lineage AS (
              SELECT id,external_content_id,parent_content_id,received_at FROM external_content_imports WHERE id=%s
              UNION ALL
              SELECT parent.id,parent.external_content_id,parent.parent_content_id,parent.received_at
              FROM external_content_imports parent JOIN import_lineage child
                ON child.parent_content_id=parent.external_content_id
            )
            SELECT i.id AS import_id,i.external_content_id,i.received_at,v.id AS import_version_id,
              v.version_number,v.title,v.body_markdown,v.content_sha256,v.author_label,v.change_reason,v.created_at,
              l.content_version_id
            FROM import_lineage i JOIN external_content_import_versions v ON v.import_id=i.id
            LEFT JOIN external_content_import_content_links l ON l.import_id=v.import_id AND l.import_version_id=v.id
            ORDER BY i.received_at DESC,v.version_number DESC,v.created_at DESC,v.id DESC""", (import_id,)
        ).fetchall()
        duplicate_import_history: list[dict[str, Any]] = []
        if latest:
            current_target = conn.execute(
                """SELECT COALESCE(origin.target_blog_id,sole.blog_id::text) AS target_blog_id
                FROM external_content_imports i
                LEFT JOIN LATERAL (SELECT payload->>'target_blog_id' AS target_blog_id FROM audit_events
                    WHERE event_type='content.import.scheduled_origin_recorded' AND payload->>'import_id'=i.id::text
                    ORDER BY created_at DESC,id DESC LIMIT 1) origin ON true
                LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN min(blog_id) END AS blog_id
                    FROM blogger_blogs WHERE active AND language_code=i.language_code) sole ON true
                WHERE i.id=%s""", (import_id,),
            ).fetchone()
            duplicate_candidates = conn.execute(
                """SELECT i.id AS import_id,i.external_content_id,i.title,i.language_code,i.source_region,
                    i.received_at,v.id AS import_version_id,v.version_number,v.content_sha256,v.body_markdown,
                    COALESCE(origin.target_blog_id,sole.blog_id::text) AS target_blog_id
                FROM external_content_imports i
                JOIN LATERAL (SELECT v.id,v.version_number,v.content_sha256,v.body_markdown FROM external_content_import_versions v
                    WHERE v.import_id=i.id ORDER BY v.version_number DESC,v.created_at DESC,v.id DESC LIMIT 1) v ON true
                LEFT JOIN LATERAL (SELECT payload->>'target_blog_id' AS target_blog_id FROM audit_events
                    WHERE event_type='content.import.scheduled_origin_recorded' AND payload->>'import_id'=i.id::text
                    ORDER BY created_at DESC,id DESC LIMIT 1) origin ON true
                LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN min(blog_id) END AS blog_id
                    FROM blogger_blogs WHERE active AND language_code=i.language_code) sole ON true
                WHERE i.language_code=%s AND i.title=%s AND i.id<>%s
                ORDER BY i.received_at DESC,i.id DESC""",
                (row["language_code"], row["title"], import_id),
            ).fetchall()
            duplicate_import_history = [dict(candidate) for candidate in duplicate_candidates
                if current_target and current_target.get("target_blog_id")
                and candidate.get("target_blog_id") == current_target.get("target_blog_id")
                and same_manuscript_content(row["title"], latest.get("body_markdown"),
                    candidate["title"], candidate.get("body_markdown"))]
            for prior_import in duplicate_import_history:
                prior_import["body_sha256"] = body_digest(prior_import.get("body_markdown"))
        assessments = conn.execute(
            "SELECT id,version_id,machine_checks,seo_checks,machine_passed,safe_html,html_sha256,assessed_at,independent_source_verification,generation_ready,publish_ready FROM external_content_import_assessments WHERE import_id=%s ORDER BY assessed_at DESC,id DESC",
            (import_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT event_type,actor,reason,details,created_at FROM external_content_import_events WHERE import_id=%s ORDER BY created_at,id",
            (import_id,),
        ).fetchall()
        reviews = conn.execute(
            "SELECT version_id,assessment_id,event_type,reviewer_label,reason,sources_examined,claims_checked,rights_reviewed,created_at FROM external_content_import_review_events WHERE import_id=%s ORDER BY created_at,id",
            (import_id,),
        ).fetchall()
        localization = conn.execute(
            "SELECT DISTINCT ON (target_language) target_language,event_type,requester_label,reason,created_at FROM external_content_import_localization_events WHERE import_id=%s ORDER BY target_language,created_at DESC,id DESC",
            (import_id,),
        ).fetchall()
        mock_publications = conn.execute(
            "SELECT id,version_id,outcome,fake_post_id,result,created_at,simulation_only,external_network_calls,real_blog_mutated FROM external_content_import_mock_publications WHERE import_id=%s ORDER BY created_at DESC,id DESC",
            (import_id,),
        ).fetchall()
        source_verifications = conn.execute(
            """SELECT DISTINCT ON (payload->>'source_id') payload,created_at
            FROM audit_events WHERE event_type='research.source.live_document_verified'
              AND payload->>'import_id'=%s
            ORDER BY payload->>'source_id',created_at DESC,id DESC""",
            (str(import_id),),
        ).fetchall()
        latest_review = next((review for review in reversed(reviews) if latest and str(review["version_id"]) == str(latest["id"])), None)
        auto_failure = conn.execute(
            """SELECT event_type,payload,id FROM audit_events
            WHERE event_type IN ('publication.auto_failure.recorded','publication.auto_failure.cleared')
              AND payload->>'import_id'=%s
              AND (%s::text IS NULL OR payload->>'content_version_id'=%s)
            ORDER BY id DESC LIMIT 1""",
            (str(import_id), str(latest.get("content_version_id")) if latest and latest.get("content_version_id") else None,
             str(latest.get("content_version_id")) if latest and latest.get("content_version_id") else None),
        ).fetchone()
        item_result = dict(row)
        from .claim_evidence import assess_claim_evidence
        claim_evidence = assess_claim_evidence(item_result, {
            str(event["payload"].get("source_id")): event["payload"] for event in source_verifications
        })
        item_result["auto_publication_failure"] = bool(auto_failure and auto_failure["event_type"] == "publication.auto_failure.recorded")
        item_result["auto_failure"] = (
            dict(auto_failure["payload"])
            if auto_failure is not None and item_result["auto_publication_failure"] else None
        )
        return {"item": item_result, "claim_evidence": claim_evidence, "latest_version": dict(latest) if latest else None,
            "versions": [dict(version) for version in versions],
            "lineage_history": [dict(version) for version in lineage_history],
            "duplicate_import_history": duplicate_import_history,
            "assessments": [dict(check) for check in assessments],
            "source_verifications": [dict(event) for event in source_verifications],
            "events": [dict(event) for event in events], "reviews": [dict(review) for review in reviews],
            "editorial_review_status": latest_review["event_type"] if latest_review else "awaiting_human_review",
            "localization_requests": [dict(request) for request in localization],
            "mock_publications": [dict(attempt) for attempt in mock_publications],
            "generator_available": False, "publish_ready": False, "generation_ready": False}


@router.post("/{import_id}/claim-evidence-assessments", status_code=201)
def record_claim_evidence_assessment(import_id: UUID) -> dict[str, Any]:
    detail = get_content_import(import_id)
    result = detail["claim_evidence"]
    with connection() as conn:
        event = conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('content.claim_evidence.assessed',%s) RETURNING id,created_at",
            (Jsonb({"import_id": str(import_id), "version_id": str((detail["latest_version"] or {}).get("id")),
                    "assessment": result, "claims_promoted": False}),),
        ).fetchone()
        if event is None:
            raise HTTPException(503, "Claim evidence audit persistence unavailable")
    return {**result, "audit_event_id": event["id"], "assessed_at": event["created_at"]}


@router.post("", status_code=201)
def submit_content_import(request: ImportSubmission) -> dict[str, Any]:
    canonical = request.item.model_dump_json(exclude_none=False)
    content_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    idempotency_key = hashlib.sha256(
        f"{request.item.generation_method}:{request.item.content_id}".encode()
    ).hexdigest()
    recommendations = language_candidates(
        request.item.source_region,
        {target.language_code: target.reader_relevance_reason for target in request.item.target_audiences},
    )
    labels = suggested_labels(request.item.category, request.item.language_code,
                              google_trends_based=request.item.google_trends_based)
    if request.item.google_trends_based and labels[0] not in request.item.blogger_labels:
        raise HTTPException(422, "Google Trends manuscript requires the locale issue label")
    with connection() as conn:
        _require_import_review_schema(conn)
        exists = conn.execute("SELECT to_regclass('public.external_content_imports') AS relation").fetchone()
        if not exists or not exists.get("relation"):
            raise HTTPException(409, "Content import migration 045 is required")
        if request.item.relation != "original":
            parent = conn.execute(
                "SELECT id,event_group_id,language_code FROM external_content_imports WHERE external_content_id=%s ORDER BY received_at,id LIMIT 1",
                (request.item.parent_content_id,),
            ).fetchone()
            if not parent:
                raise HTTPException(409, "The referenced parent import does not exist")
            if parent["event_group_id"] != request.item.event_group_id:
                raise HTTPException(409, "Derived import must remain in the parent's event group")
            if request.item.relation == "localized" and parent["language_code"] == request.item.language_code:
                raise HTTPException(422, "Localized import must use a different language")
            if request.item.relation == "revision" and parent["language_code"] != request.item.language_code:
                raise HTTPException(422, "A revision must keep the parent manuscript language")
        row = conn.execute(
            """INSERT INTO external_content_imports(
                external_content_id,event_group_id,research_package_id,parent_content_id,relation,
                source_region,language_code,target_audiences,category,title,body_markdown,source_ids,
                sources,claims,fact_checked_at,seo_metadata,blogger_labels,generation_method,model_name,
                generated_at,submitted_by,content_sha256,idempotency_key,state)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'awaiting_human_review')
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id,received_at,state""",
            (request.item.content_id, request.item.event_group_id, request.item.research_package_id,
             request.item.parent_content_id, request.item.relation, request.item.source_region,
             request.item.language_code, Jsonb([target.model_dump(mode="json") for target in request.item.target_audiences]),
             request.item.category, request.item.title, request.item.body_markdown, Jsonb(request.item.source_ids),
             Jsonb([source.model_dump(mode="json") for source in request.item.sources]),
             Jsonb([claim.model_dump(mode="json") for claim in request.item.claims]), request.item.fact_checked_at,
             Jsonb(request.item.seo.model_dump(mode="json")), Jsonb(request.item.blogger_labels),
             request.item.generation_method, request.item.model_name, request.item.generated_at,
             request.submitted_by, content_sha256, idempotency_key),
        ).fetchone()
        duplicate = row is None
        if duplicate:
            row = conn.execute("SELECT id,received_at,state,content_sha256 FROM external_content_imports WHERE idempotency_key=%s", (idempotency_key,)).fetchone()
            if row is None or row["content_sha256"] != content_sha256:
                raise HTTPException(409, "Content ID already imported with different contents")
        if row is None:
            raise HTTPException(503, "Content import persistence unavailable")
        content_version_id = None
        if not duplicate:
            version_sha = _version_digest(
                request.item.title, request.item.body_markdown,
                request.item.seo.model_dump(mode="json"), request.item.blogger_labels,
            )
            initial_version = conn.execute(
                """INSERT INTO external_content_import_versions(import_id,version_number,title,body_markdown,
                    seo_metadata,blogger_labels,content_sha256,author_label,change_reason)
                VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(import_id,version_number) DO NOTHING RETURNING id""",
                (row["id"], request.item.title, request.item.body_markdown,
                 Jsonb(request.item.seo.model_dump(mode="json")), Jsonb(request.item.blogger_labels),
                 version_sha, request.submitted_by, "Initial immutable imported version"),
            ).fetchone()
            if not initial_version:
                initial_version = conn.execute(
                    "SELECT id FROM external_content_import_versions WHERE import_id=%s AND version_number=1",
                    (row["id"],),
                ).fetchone()
            if not initial_version:
                raise HTTPException(503, "Initial import version could not be stored")
            imported = conn.execute("SELECT * FROM external_content_imports WHERE id=%s", (row["id"],)).fetchone()
            assert imported is not None
            parent_content_version_id = None
            if request.item.parent_content_id:
                assert parent is not None
                parent_link = conn.execute(
                    """SELECT l.content_version_id FROM external_content_imports p
                    JOIN external_content_import_versions pv ON pv.import_id=p.id
                    JOIN external_content_import_content_links l ON l.import_id=pv.import_id AND l.import_version_id=pv.id
                    WHERE p.id=%s ORDER BY pv.version_number DESC LIMIT 1""", (parent["id"],),
                ).fetchone()
                if not parent_link:
                    raise HTTPException(409, "The parent manuscript has no native version mapping")
                parent_content_version_id = parent_link["content_version_id"]
            content_version_id = _link_manuscript_version(conn, row["id"], imported, initial_version["id"],
                request.item.title, request.item.body_markdown, parent_content_version_id)
            details = {"external_content_id": request.item.content_id, "event_group_id": request.item.event_group_id,
                "language_code": request.item.language_code, "source_region": request.item.source_region,
                "category": request.item.category, "content_sha256": content_sha256,
                "reader_language_decisions": recommendations, "labels": labels,
                "source_fetch_performed": False, "provider_called": False, "blogger_write_performed": False,
                "content_version_id": str(content_version_id),
                "publish_ready": False, "generation_ready": False}
            conn.execute(
                """INSERT INTO external_content_import_events(import_id,event_key,event_type,actor,reason,details)
                VALUES (%s,%s,'received',%s,%s,%s)""",
                (row["id"], f"import_{idempotency_key}", request.submitted_by,
                 "External manuscript accepted into the untrusted review queue; human source and claim review required.", Jsonb(details)),
            )
            conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('content.import.received',%s)", (Jsonb({"import_id": str(row["id"]), **details}),))
        else:
            existing_link = conn.execute(
                """SELECT l.content_version_id FROM external_content_import_versions v
                JOIN external_content_import_content_links l ON l.import_id=v.import_id AND l.import_version_id=v.id
                WHERE v.import_id=%s ORDER BY v.version_number DESC LIMIT 1""", (row["id"],),
            ).fetchone()
            content_version_id = existing_link["content_version_id"] if existing_link else None
        if request.manual_automation_origin:
            manual_origin_event = _record_manual_automation_origin(
                conn, import_id=row["id"], content_version_id=content_version_id,
                language_code=request.item.language_code, origin=request.manual_automation_origin,
            )
        else:
            manual_origin_event = None
        return {"import_id": str(row["id"]), "state": row["state"], "duplicate": duplicate,
            "content_sha256": content_sha256, "category": request.item.category,
            "suggested_labels": labels, "reader_language_decisions": recommendations,
            "generation_ready": False, "publish_ready": False, "provider_called": False,
            "blogger_write_performed": False, "source_fetch_performed": False,
            "human_review_required": True,
            "content_version_id": str(content_version_id) if content_version_id else None,
            "manual_automation_audit_event_id": str(manual_origin_event["id"]) if manual_origin_event else None}


def _record_manual_automation_origin(
    conn: psycopg.Connection[dict[str, Any]],
    *,
    import_id: UUID,
    content_version_id: UUID | None,
    language_code: str,
    origin: ManualAutomationOrigin,
) -> dict[str, Any]:
    """Append one idempotent audit record; manual origin grants no publish rights."""
    if content_version_id is None:
        raise HTTPException(409, "Manual automation import has no linked content version")
    imported = conn.execute(
        "SELECT generation_method FROM external_content_imports WHERE id=%s", (import_id,)
    ).fetchone()
    if not imported or imported["generation_method"] != "manual_codex_import":
        raise HTTPException(409, "Manual automation provenance requires a manual Codex import")
    event_key = origin.manual_run_id
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (event_key,))
    origin_payload = origin.model_dump(mode="json", exclude_none=False)
    origin_sha256 = hashlib.sha256(
        json.dumps(origin_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing = conn.execute(
        """SELECT id,payload FROM audit_events
        WHERE event_type='content.import.manual_automation_origin_recorded'
          AND payload->>'manual_run_id'=%s""",
        (event_key,),
    ).fetchone()
    if existing:
        if (existing["payload"].get("origin_sha256") != origin_sha256
                or existing["payload"].get("import_id") != str(import_id)):
            raise HTTPException(409, "Manual run ID was already recorded with different import data")
        return {"id": existing["id"], "duplicate": True}
    payload = {
        **origin_payload,
        "manual_run_id": event_key,
        "import_id": str(import_id),
        "content_version_id": str(content_version_id),
        "language_code": language_code,
        "origin_sha256": origin_sha256,
        "provenance_self_reported": True,
        "execution_context_server_verified": False,
        "scheduled_origin_claimed": False,
        "auto_publication_enabled": False,
        "publish_ready": False,
        "blogger_write_performed": False,
    }
    inserted = conn.execute(
        """INSERT INTO audit_events(event_type,language_code,payload)
        VALUES ('content.import.manual_automation_origin_recorded',%s,%s) RETURNING id""",
        (language_code, Jsonb(payload)),
    ).fetchone()
    if not inserted:
        raise HTTPException(503, "Manual automation audit event could not be stored")
    return {"id": inserted["id"], "duplicate": False}


@router.post("/{import_id}/scheduled-origin", status_code=201)
def record_scheduled_import_origin(
    import_id: UUID, request: ScheduledImportOrigin
) -> dict[str, Any]:
    """Append an idempotent audit event for an untrusted scheduled-task claim."""
    try:
        return _record_scheduled_import_origin(import_id, request)
    except psycopg.Error as exc:
        # Keep the database message, values, and identifiers out of HTTP/audit
        # output while exposing enough SQLSTATE classification to operate the
        # retry safely.
        category = {
            "42501": "insufficient_privilege",
            "23503": "foreign_key_conflict",
            "23505": "duplicate_conflict",
            "23514": "constraint_conflict",
            "42703": "schema_mismatch",
            "42P01": "missing_relation",
            "40001": "serialization_conflict",
            "40P01": "deadlock_conflict",
        }.get(exc.sqlstate or "", "database_operation_unavailable")
        sqlstate = exc.sqlstate or "unknown"
        raise HTTPException(
            503,
            f"scheduled_origin_database_error:{category}:sqlstate_{sqlstate}",
        ) from None


def _record_scheduled_import_origin(
    import_id: UUID, request: ScheduledImportOrigin
) -> dict[str, Any]:
    canonical = request.model_dump_json(exclude_none=False)
    origin_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    event_key = hashlib.sha256(
        f"scheduled-origin:{request.task_id}:{request.occurrence_id}".encode()
    ).hexdigest()
    target_url = f"https://{urlsplit(str(request.target_blog_url)).hostname}".lower()
    with connection() as conn:
        imported = conn.execute(
            "SELECT generation_method,language_code FROM external_content_imports WHERE id=%s",
            (import_id,),
        ).fetchone()
        if not imported:
            raise HTTPException(404, "Scheduled import was not found")
        if imported["generation_method"] != "chatgpt_scheduled_export":
            raise HTTPException(409, "Import was not received as a scheduled export")
        if imported["language_code"] != request.target_language_code:
            raise HTTPException(409, "Scheduled target language does not match the imported manuscript")
        blog = conn.execute(
            """SELECT id,url,language_code FROM blogger_blogs
            WHERE blog_id=%s AND language_code=%s AND active""",
            (request.target_blog_id, request.target_language_code),
        ).fetchone()
        if not blog or str(blog["url"]).rstrip("/").lower() != target_url:
            raise HTTPException(409, "Scheduled target does not match an active registered Blogger blog")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (event_key,))
        existing = conn.execute(
            """SELECT id,payload FROM audit_events
            WHERE event_type='content.import.scheduled_origin_recorded'
              AND payload->>'event_key'=%s""",
            (event_key,),
        ).fetchone()
        if existing:
            if (
                existing["payload"].get("origin_sha256") != origin_sha256
                or existing["payload"].get("import_id") != str(import_id)
            ):
                raise HTTPException(409, "Scheduled occurrence was already recorded with different metadata")
            return {"audit_event_id": existing["id"], "duplicate": True,
                    "provenance_verified": False, "auto_publication_enabled": False}
        payload = {
            "event_key": event_key,
            "import_id": str(import_id),
            "task_type": request.task_type,
            "task_id": request.task_id,
            "occurrence_id": request.occurrence_id,
            "occurrence_id_source": request.occurrence_id_source or "legacy_self_reported",
            "scheduler_occurrence_id": request.scheduler_occurrence_id,
            "automation_id": request.automation_id,
            "scheduled_slot": request.scheduled_slot.isoformat() if request.scheduled_slot else None,
            "occurrence_timezone": "Asia/Seoul" if request.occurrence_id_source == "project_derived_kst_slot" else None,
            "local_duplicate_status": request.local_duplicate_status,
            "remote_duplicate_status": request.remote_duplicate_status,
            "remote_failure_code": request.remote_failure_code,
            "draft_import_allowed": request.draft_import_allowed,
            "publication_recheck_required": request.publication_recheck_required,
            "publication_retry_status": request.publication_retry_status,
            "executed_at": request.executed_at.isoformat(),
            "market_date": request.market_date.isoformat() if request.market_date else None,
            "target_language_code": request.target_language_code,
            "target_blog_id": request.target_blog_id,
            "target_blog_url": target_url,
            "source_as_of": request.source_as_of.isoformat(),
            "inbox_file_name": request.inbox_file_name,
            "inbox_file_sha256": request.inbox_file_sha256,
            "origin_sha256": origin_sha256,
            "provenance_self_reported": True,
            "external_task_identity_verified": False,
            "generation_ready": False,
            "publish_ready": False,
            "blogger_write_performed": False,
        }
        row = conn.execute(
            """INSERT INTO audit_events(event_type,blog_id,language_code,payload)
            VALUES ('content.import.scheduled_origin_recorded',%s,%s,%s) RETURNING id""",
            (blog["id"], request.target_language_code, Jsonb(payload)),
        ).fetchone()
        if not row:
            raise HTTPException(503, "Scheduled import audit event could not be stored")
        return {"audit_event_id": row["id"], "duplicate": False,
                "provenance_verified": False, "auto_publication_enabled": False}


@router.post("/{import_id}/assessment", status_code=201)
def assess_import(import_id: UUID, request: ImportAssessmentRequest) -> dict[str, Any]:
    from .ai import Draft
    from .article_quality import evaluate
    from .editorial_html import markdown_to_blogger_html, sanitize_editorial_html
    from .editorial_seo import EditorialSeoMetadata, SeoSource, evaluate_seo_readiness

    with connection() as conn:
        _require_import_review_schema(conn)
        imported = _require_import(conn, import_id)
        version = _latest_version(conn, import_id) if request.version_id is None else conn.execute(
            "SELECT * FROM external_content_import_versions WHERE import_id=%s AND id=%s",
            (import_id, request.version_id),
        ).fetchone()
        if version is None:
            raise HTTPException(404, "Imported version not found")
        seo_raw = version["seo_metadata"]
        seo_input = SeoMetadata.model_validate(seo_raw)
        source_rows = imported["sources"]
        claims = imported["claims"]
        live_rows = conn.execute(
            """SELECT DISTINCT ON (payload->>'source_id') payload FROM audit_events
            WHERE event_type='research.source.live_document_verified' AND payload->>'import_id'=%s
            ORDER BY payload->>'source_id',created_at DESC,id DESC""",
            (str(import_id),),
        ).fetchall()
        live_by_source = {
            str(row["payload"].get("source_id")): row["payload"] for row in live_rows
        }
        source_evidence: dict[str, list[str]] = {str(item["source_id"]): [] for item in source_rows}
        for claim in claims:
            for source_id in claim["source_ids"]:
                source_evidence.setdefault(str(source_id), []).append(str(claim["evidence_excerpt"]))
        # Source fetch verification is append-only provenance, not semantic or
        # rights approval. Use only bounded excerpts recorded for this source ID
        # to assess the current article revision against the fetched document.
        for source_id, verification in live_by_source.items():
            excerpts = verification.get("verified_claim_evidence", [])
            if isinstance(excerpts, list):
                source_evidence.setdefault(source_id, []).extend(
                    excerpt[:1200] for excerpt in excerpts
                    if isinstance(excerpt, str) and excerpt.strip()
                )
        quality_sources = []
        for source in source_rows:
            verification = live_by_source.get(str(source["source_id"]), {})
            published_at = str(source.get("published_at") or "")
            if not published_at and verification.get("source_published_date"):
                published_at = str(verification["source_published_date"])
            if published_at:
                try:
                    published_date = datetime.fromisoformat(published_at).date()
                    published_at = f"{published_date.year}년 {published_date.month}월 {published_date.day}일"
                except ValueError:
                    pass
            normalized_facts = verification.get("normalized_facts", [])
            normalized_evidence = []
            if isinstance(normalized_facts, list):
                normalized_evidence = [
                    str(fact.get("normalized_value", ""))
                    for fact in normalized_facts
                    if isinstance(fact, dict) and fact.get("normalized_value")
                ]
            quality_sources.append({
                "id": str(source["source_id"]), "url": str(source["url"]),
                "source_name": str(source["organization"]),
                "evidence": " ".join(source_evidence.get(str(source["source_id"]), []) + normalized_evidence),
                "rights": str(source["rights_note"]),
                "published_at": published_at,
            })
        draft = Draft(
            title=str(version["title"]), body=str(version["body_markdown"]),
            summary=seo_input.core_answer, keywords=seo_input.primary_terms[:6],
            source_ids=[str(source["source_id"]) for source in source_rows],
        )
        machine = evaluate(draft, quality_sources, str(imported["language_code"]),
                           datetime.now(UTC).date().isoformat(), len(claims))
        try:
            safe_html = markdown_to_blogger_html(draft.body, post_title=draft.title, summary=seo_input.search_description)
            safe_html, plain_text = sanitize_editorial_html(safe_html, post_title=draft.title)
        except ValueError as exc:
            raise HTTPException(422, "Editorial HTML validation failed") from exc
        seo_metadata = EditorialSeoMetadata(
            language_code=str(imported["language_code"]),
            target_region=(imported["target_audiences"][0].get("target_region") if imported["target_audiences"] else None),
            search_intent=None, primary_keyword=seo_input.primary_terms[0] if seo_input.primary_terms else None,
            related_terms=seo_input.related_terms[:6], seo_title_candidates=[seo_input.seo_title],
            seo_title=seo_input.seo_title, search_description=seo_input.search_description,
            core_question=seo_input.core_question, core_answer=seo_input.core_answer,
            category=str(imported["category"]), blogger_labels=list(version["blogger_labels"]),
            author=None, sources=[
                SeoSource(title=str(source["title"]), url=str(source["url"]))
                for source in source_rows
            ], official_sources=[
                SeoSource(
                    title=str(source["title"]), url=str(source["url"]),
                    official_status=("verified" if (
                        (urlsplit(str(source["url"])).hostname or "").casefold() in OFFICIAL_SOURCE_HOSTS
                        and live_by_source.get(str(source["source_id"]), {}).get("url") == str(source["url"])
                        and live_by_source.get(str(source["source_id"]), {}).get("source_host") == urlsplit(str(source["url"])).hostname
                        and live_by_source.get(str(source["source_id"]), {}).get("http_status") == 200
                    ) else "unverified"),
                ) for source in source_rows
                if (urlsplit(str(source["url"])).hostname or "").casefold() in OFFICIAL_SOURCE_HOSTS
            ],
            fact_verified_at=None, editorial_status="unknown",
        )
        seo_checks = evaluate_seo_readiness(seo_metadata, title=draft.title, plain_text=plain_text,
            safe_html=safe_html, source_body=draft.body, body_format="markdown")
        # This is a syntax/heuristic result only. It does not verify source contents,
        # claim entailment, rights, naturalness, or publication eligibility.
        machine_passed = bool(machine["machine_passed"])
        html_hash = hashlib.sha256(safe_html.encode("utf-8")).hexdigest()
        record = conn.execute(
            """INSERT INTO external_content_import_assessments(import_id,version_id,machine_checks,seo_checks,
                machine_passed,safe_html,html_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id,assessed_at""",
            (import_id, version["id"], Jsonb(machine), Jsonb(seo_checks), machine_passed, safe_html, html_hash),
        ).fetchone()
        assert record is not None
        _audit(conn, "content.import.assessed", {"import_id": str(import_id), "version_id": str(version["id"]),
            "assessment_id": str(record["id"]), "machine_passed": machine_passed,
            "independent_source_verification": False, "generation_ready": False, "publish_ready": False})
        return {"assessment_id": str(record["id"]), "version_id": str(version["id"]),
            "machine_checks": machine, "seo_checks": seo_checks, "machine_passed": machine_passed,
            "safe_html": safe_html, "html_sha256": html_hash, "assessed_at": record["assessed_at"],
            "independent_source_verification": False, "requires_human_review": True,
            "generation_ready": False, "publish_ready": False}


@router.post("/{import_id}/live-source-evidence", status_code=201)
def capture_scheduled_live_source_evidence(import_id: UUID) -> dict[str, Any]:
    """Capture provenance only for exact URLs in the reviewed scheduled catalog."""
    from .scheduled_source_evidence import capture_import_sources

    try:
        return capture_import_sources(import_id)
    except ValueError as exc:
        if str(exc) == "scheduled_import_not_found":
            raise HTTPException(404, "Scheduled import not found") from exc
        raise HTTPException(409, "Scheduled source capture was not accepted") from exc


@router.post("/{import_id}/versions", status_code=201)
def create_import_version(import_id: UUID, request: ImportVersionRequest) -> dict[str, Any]:
    with connection() as conn:
        _require_import_review_schema(conn)
        imported = _require_import(conn, import_id)
        latest = _latest_version(conn, import_id)
        if str(latest["id"]) != str(request.base_version_id):
            raise HTTPException(409, "This manuscript changed after editing began; reload the latest version.")
        # Existing schema stores the validated labels, not the boolean topic-origin
        # input. Permit the existing category set plus its locale issue label while
        # preserving the exact labels the reviewer supplied.
        allowed_labels = suggested_labels(str(imported["category"]), str(imported["language_code"]),
            google_trends_based=True)
        if any(label not in allowed_labels for label in request.blogger_labels):
            raise HTTPException(422, "Unrecognized or unreviewed Blogger label")
        seo = request.seo_metadata.model_dump(mode="json")
        digest = _version_digest(request.title, request.body_markdown, seo, request.blogger_labels)
        duplicate = conn.execute(
            "SELECT id,version_number FROM external_content_import_versions WHERE import_id=%s AND content_sha256=%s",
            (import_id, digest),
        ).fetchone()
        if duplicate:
            return {"version_id": str(duplicate["id"]), "version_number": duplicate["version_number"], "duplicate": True, "publish_ready": False}
        next_number = int(latest["version_number"]) + 1
        version = conn.execute(
            """INSERT INTO external_content_import_versions(import_id,version_number,parent_version_id,title,
              body_markdown,seo_metadata,blogger_labels,content_sha256,author_label,change_reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,version_number,content_sha256,created_at""",
            (import_id, next_number, latest["id"], request.title, request.body_markdown,
             Jsonb(seo), Jsonb(request.blogger_labels), digest, request.author_label, request.reason),
        ).fetchone()
        assert version is not None
        previous_link = conn.execute(
            "SELECT content_version_id FROM external_content_import_content_links WHERE import_id=%s AND import_version_id=%s",
            (import_id, latest["id"]),
        ).fetchone()
        if not previous_link:
            raise HTTPException(409, "The prior imported version has no manuscript model mapping")
        content_version_id = _link_manuscript_version(
            conn, import_id, imported, version["id"], request.title, request.body_markdown,
            previous_link["content_version_id"],
        )
        _audit(conn, "content.import.version_created", {"import_id": str(import_id), "version_id": str(version["id"]),
            "parent_version_id": str(latest["id"]), "version_number": next_number,
            "content_version_id": str(content_version_id), "content_sha256": digest,
            "author_label": request.author_label, "reason": request.reason[:300]})
        return {"version_id": str(version["id"]), "version_number": next_number,
            "content_version_id": str(content_version_id),
            "content_sha256": digest, "created_at": version["created_at"], "duplicate": False,
            "generation_ready": False, "publish_ready": False}


def prepare_scheduled_publishable_version(import_id: UUID) -> dict[str, Any]:
    """Create an immutable scheduled-only revision that removes unsupported blocks.

    A sanitized revision is never created when the source evidence cannot support
    at least two substantive paragraphs. Existing versions remain immutable.
    """
    from .scheduled_auto_verification import sanitize_scheduled_body, verified_scheduled_claim_ids

    with connection() as conn:
        imported = _require_import(conn, import_id)
        if imported["generation_method"] != "chatgpt_scheduled_export":
            return {"status": "not_scheduled"}
        policy = conn.execute("SELECT action FROM scheduled_publication_policy_events ORDER BY id DESC LIMIT 1").fetchone()
        global_state = conn.execute(
            "SELECT emergency_stopped FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
        ).fetchone()
        if not policy or policy["action"] != "enabled" or not global_state or global_state["emergency_stopped"]:
            return {"status": "policy_off_or_stopped"}
        latest = _latest_version(conn, import_id)
        proofs = conn.execute(
            """SELECT DISTINCT ON (payload->>'source_id') payload FROM audit_events
            WHERE event_type='research.source.live_document_verified' AND payload->>'import_id'=%s
            ORDER BY payload->>'source_id',id DESC""", (str(import_id),),
        ).fetchall()
        proof_by_id = {str(row["payload"].get("source_id")): row["payload"] for row in proofs}
        normalized_proofs = {source_id: {
            **proof, "source_url": proof.get("source_url") or proof.get("url"),
            "source_body_sha256": proof.get("source_body_sha256") or proof.get("body_sha256"),
        } for source_id, proof in proof_by_id.items()}
        verified_claim_ids = verified_scheduled_claim_ids(imported, normalized_proofs)
        manifest = conn.execute(
            """SELECT payload FROM audit_events WHERE event_type='publication.scheduled_auto.sanitization_revision_created'
            AND payload->>'output_version_id'=%s AND payload->>'output_sha256'=%s ORDER BY id DESC LIMIT 1""",
            (str(latest['id']), hashlib.sha256(str(latest['body_markdown']).encode('utf-8')).hexdigest()),
        ).fetchone()
        retained_claims = imported['claims'] or []
        if manifest:
            retained_ids = set(manifest['payload'].get('retained_claim_ids', []))
            retained_claims = [claim for claim in retained_claims if claim.get('claim_id') in retained_ids]
        sanitized = sanitize_scheduled_body(
            str(latest["body_markdown"]), retained_claims,
            verified_claim_ids=verified_claim_ids,
        )
        if not sanitized["changed"]:
            return {"status": "unchanged", "version_id": str(latest["id"]),
                    "body_sha256": sanitized["output_sha256"]}
        if (sanitized["substantive_blocks_remaining"] < 2
            or len(sanitized["body_markdown"]) < 100):
            prior = conn.execute(
                """SELECT 1 FROM audit_events WHERE event_type='publication.scheduled_auto.sanitization_held'
                AND payload->>'import_id'=%s AND payload->>'version_id'=%s AND payload->>'input_sha256'=%s LIMIT 1""",
                (str(import_id), str(latest["id"]), sanitized["input_sha256"]),
            ).fetchone()
            if not prior:
                _audit(conn, "publication.scheduled_auto.sanitization_held", {
                    "import_id": str(import_id), "version_id": str(latest["id"]),
                    "input_sha256": sanitized["input_sha256"], "output_sha256": sanitized["output_sha256"],
                    "removed_blocks": sanitized["removed_blocks"],
                    "verified_claim_ids": sorted(verified_claim_ids),
                    "reason": "insufficient_supported_body_after_sanitization",
                    "policy_version": sanitized["policy_version"],
                })
            return {"status": "held", "reason": "insufficient_supported_body_after_sanitization",
                    "removed_block_count": len(sanitized["removed_blocks"])}
        base_id = latest["id"]
        title = str(latest["title"])
        seo = SeoMetadata.model_validate(latest["seo_metadata"])
        labels = list(latest["blogger_labels"] or [])

    revision = create_import_version(import_id, ImportVersionRequest(
        base_version_id=base_id, title=title, body_markdown=sanitized["body_markdown"],
        seo_metadata=seo, blogger_labels=labels, author_label="scheduled-policy-sanitizer",
        reason="P5-CODEX-052: remove paragraphs whose cited claims lack current source evidence",
    ))
    if revision.get("duplicate"):
        return {"status": "duplicate_revision", "version_id": revision["version_id"]}
    version_id = UUID(revision["version_id"])
    try:
        assessment = assess_import(import_id, ImportAssessmentRequest(version_id=version_id))
    except (HTTPException, ValueError, ValidationError, psycopg.Error) as exc:
        with connection() as conn:
            _audit(conn, "publication.scheduled_auto.sanitization_assessment_failed", {
                "import_id": str(import_id), "version_id": str(version_id),
                "input_sha256": sanitized["input_sha256"], "output_sha256": sanitized["output_sha256"],
                "error_category": type(exc).__name__,
                "policy_version": sanitized["policy_version"], "publish_ready": False,
            })
        return {"status": "held", "reason": "sanitized_revision_assessment_failed",
                "version_id": str(version_id)}
    retained_source_ids = sorted(set(re.findall(r"\[source:([A-Za-z0-9_-]+)\]", sanitized["body_markdown"])))
    retained_claim_ids = sorted({
        str(claim.get("claim_id")) for claim in imported["claims"]
        if isinstance(claim, dict) and str(claim.get("claim_id")) in verified_claim_ids
        and {str(x) for x in claim.get("source_ids") or []}.intersection(retained_source_ids)
    })
    with connection() as conn:
        _audit(conn, "publication.scheduled_auto.sanitization_revision_created", {
            "import_id": str(import_id), "input_version_id": str(base_id),
            "output_version_id": str(version_id), "content_version_id": revision["content_version_id"],
            "input_sha256": sanitized["input_sha256"],
            "output_sha256": sanitized["output_sha256"],
            "retained_source_ids": retained_source_ids,
            "retained_claim_ids": retained_claim_ids,
            "removed_blocks": sanitized["removed_blocks"],
            "assessment_id": assessment["assessment_id"],
            "machine_passed": assessment["machine_passed"],
            "policy_version": sanitized["policy_version"], "publish_ready": False,
        })
    return {"status": "revision_created", "version_id": str(version_id),
            "content_version_id": revision["content_version_id"],
            "body_sha256": sanitized["output_sha256"],
            "removed_block_count": len(sanitized["removed_blocks"]),
            "machine_passed": assessment["machine_passed"]}


@router.post("/{import_id}/reviews", status_code=201)
def record_import_review(import_id: UUID, request: ImportReviewRequest) -> dict[str, Any]:
    with connection() as conn:
        _require_import_review_schema(conn)
        _require_import(conn, import_id)
        latest = _latest_version(conn, import_id)
        if str(latest["id"]) != str(request.version_id):
            raise HTTPException(409, "Review must target the latest immutable version")
        assessment = conn.execute(
            "SELECT id,machine_passed FROM external_content_import_assessments WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1",
            (import_id, request.version_id),
        ).fetchone()
        if request.disposition == "editorial_review_passed":
            if not assessment or not assessment["machine_passed"]:
                raise HTTPException(409, "The current version has no passing deterministic quality assessment")
            if not (request.sources_examined and request.claims_checked and request.rights_reviewed):
                raise HTTPException(422, "A review pass requires explicit source, claim, and rights review attestations")
        row = conn.execute(
            """INSERT INTO external_content_import_review_events(import_id,version_id,assessment_id,event_type,
              reviewer_label,reason,sources_examined,claims_checked,rights_reviewed)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,created_at""",
            (import_id, request.version_id, assessment["id"] if assessment else None, request.disposition,
             request.reviewer_label, request.reason, request.sources_examined, request.claims_checked, request.rights_reviewed),
        ).fetchone()
        assert row is not None
        _audit(conn, f"content.import.{request.disposition}", {"import_id": str(import_id),
            "version_id": str(request.version_id), "review_event_id": str(row["id"]),
            "reviewer_label": request.reviewer_label, "reason": request.reason[:300],
            "generation_ready": False, "publish_ready": False})
        return {"review_event_id": str(row["id"]), "status": request.disposition,
            "created_at": row["created_at"], "generation_ready": False, "publish_ready": False}


@router.get("/{import_id}/localizations")
def list_import_localizations(import_id: UUID) -> dict[str, Any]:
    with connection() as conn:
        _require_import_review_schema(conn)
        _require_import(conn, import_id)
        rows = conn.execute(
            """SELECT DISTINCT ON (target_language) target_language,event_type,requester_label,reason,created_at
            FROM external_content_import_localization_events WHERE import_id=%s
            ORDER BY target_language,created_at DESC,id DESC""", (import_id,),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "generation_provider_available": False,
            "provider_status": "awaiting_external_provider", "publish_ready": False}


@router.post("/{import_id}/localizations", status_code=201)
def request_import_localization(import_id: UUID, request: LocalizationRequest) -> dict[str, Any]:
    with connection() as conn:
        _require_import_review_schema(conn)
        imported = _require_import(conn, import_id)
        if request.target_language == imported["language_code"]:
            raise HTTPException(422, "Localization target must differ from the source language")
        existing_language = conn.execute(
            "SELECT 1 FROM external_content_imports WHERE event_group_id=%s AND language_code=%s LIMIT 1",
            (imported["event_group_id"], request.target_language),
        ).fetchone()
        if existing_language:
            raise HTTPException(409, "This event group already has an import in the selected language")
        key = hashlib.sha256(f"request:{import_id}:{request.target_language}:{request.requester_label}:{request.reason}".encode()).hexdigest()
        row = conn.execute(
            """INSERT INTO external_content_import_localization_events(import_id,target_language,event_type,
              requester_label,reason,idempotency_key) VALUES (%s,%s,'requested',%s,%s,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id,created_at""",
            (import_id, request.target_language, request.requester_label, request.reason, key),
        ).fetchone()
        duplicate = row is None
        if duplicate:
            row = conn.execute("SELECT id,created_at FROM external_content_import_localization_events WHERE idempotency_key=%s", (key,)).fetchone()
        assert row is not None
        if not duplicate:
            _audit(conn, "content.import.localization_requested", {"import_id": str(import_id),
                "target_language": request.target_language, "requester_label": request.requester_label,
                "reason": request.reason[:300], "provider_available": False})
        return {"request_id": str(row["id"]), "target_language": request.target_language,
            "status": "awaiting_external_provider", "duplicate": duplicate,
            "generation_provider_available": False, "publish_ready": False}


@router.post("/{import_id}/localizations/{target_language}/cancel", status_code=201)
def cancel_import_localization(import_id: UUID, target_language: str, request: LocalizationCancelRequest) -> dict[str, Any]:
    if target_language not in LANGUAGES:
        raise HTTPException(422, "Unsupported localization language")
    with connection() as conn:
        _require_import_review_schema(conn)
        _require_import(conn, import_id)
        latest = conn.execute(
            "SELECT event_type FROM external_content_import_localization_events WHERE import_id=%s AND target_language=%s ORDER BY created_at DESC,id DESC LIMIT 1",
            (import_id, target_language),
        ).fetchone()
        if not latest or latest["event_type"] != "requested":
            raise HTTPException(409, "No active localization request exists for this language")
        key = hashlib.sha256(f"cancel:{import_id}:{target_language}:{request.requester_label}:{request.reason}".encode()).hexdigest()
        row = conn.execute(
            """INSERT INTO external_content_import_localization_events(import_id,target_language,event_type,
              requester_label,reason,idempotency_key) VALUES (%s,%s,'cancelled',%s,%s,%s)
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
            (import_id, target_language, request.requester_label, request.reason, key),
        ).fetchone()
        if row:
            _audit(conn, "content.import.localization_cancelled", {"import_id": str(import_id),
                "target_language": target_language, "requester_label": request.requester_label, "reason": request.reason[:300]})
        return {"status": "cancelled", "target_language": target_language,
            "generation_provider_available": False, "publish_ready": False}


@router.post("/{import_id}/mock-publications", status_code=201)
def simulate_import_publication(import_id: UUID, request: MockPublicationRequest) -> dict[str, Any]:
    from .publications import FakeBloggerPublisher

    with connection() as conn:
        _require_import_review_schema(conn)
        _require_import(conn, import_id)
        version = conn.execute(
            "SELECT id FROM external_content_import_versions WHERE import_id=%s AND id=%s",
            (import_id, request.version_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Imported version not found")
        existing = conn.execute("SELECT * FROM external_content_import_mock_publications WHERE idempotency_key=%s", (request.idempotency_key,)).fetchone()
        if existing:
            if str(existing["import_id"]) != str(import_id) or str(existing["version_id"]) != str(request.version_id):
                raise HTTPException(409, "Mock idempotency key conflict")
            return {**dict(existing), "duplicate": True, "simulation_only": True,
                "external_network_calls": 0, "real_blog_mutated": False, "publish_ready": False}
        review = conn.execute(
            "SELECT event_type FROM external_content_import_review_events WHERE import_id=%s AND version_id=%s ORDER BY created_at DESC,id DESC LIMIT 1",
            (import_id, request.version_id),
        ).fetchone()
        assessment = conn.execute(
            "SELECT machine_passed FROM external_content_import_assessments WHERE import_id=%s AND version_id=%s ORDER BY assessed_at DESC,id DESC LIMIT 1",
            (import_id, request.version_id),
        ).fetchone()
        if not review or review["event_type"] != "editorial_review_passed" or not assessment or not assessment["machine_passed"]:
            raise HTTPException(409, "Mock publisher requires the latest passing assessment and explicit editorial review")
        result = FakeBloggerPublisher().publish(request.scenario)
        row = conn.execute(
            """INSERT INTO external_content_import_mock_publications(import_id,version_id,idempotency_key,
              outcome,fake_post_id,result) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,created_at""",
            (import_id, request.version_id, request.idempotency_key, result["outcome"], result["fake_post_id"], Jsonb(result)),
        ).fetchone()
        assert row is not None
        _audit(conn, "content.import.mock_publication", {"import_id": str(import_id),
            "version_id": str(request.version_id), "attempt_id": str(row["id"]),
            "scenario": request.scenario, "outcome": result["outcome"],
            "simulation_only": True, "external_network_calls": 0, "real_blog_mutated": False,
            "publish_ready": False})
        return {"attempt_id": str(row["id"]), "created_at": row["created_at"], **result,
            "duplicate": False, "publish_ready": False}
