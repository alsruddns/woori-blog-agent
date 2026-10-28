"""Strict, idempotent intake for externally authored manuscripts.

Imports are stored as untrusted review material. They are never converted to a
publishable manuscript and never call a generator, network source, or Blogger.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .db import connection
from .editorial_taxonomy import (
    EDITORIAL_CATEGORIES,
    ISSUE_LABELS,
    language_candidates,
    suggested_labels,
)

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
    generation_method: Literal["manual_codex_import", "chatgpt_scheduled_export", "other_external_export"]
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


@router.get("")
def list_content_imports(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    with connection() as conn:
        exists = conn.execute("SELECT to_regclass('public.external_content_imports') AS relation").fetchone()
        if not exists or not exists.get("relation"):
            raise HTTPException(409, "Content import migration 045 is required")
        rows = conn.execute(
            """SELECT id,external_content_id,event_group_id,language_code,source_region,category,
                title,content_sha256,state,received_at,generation_method,model_name
            FROM external_content_imports ORDER BY received_at DESC,id DESC LIMIT %s""", (limit,),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "categories": [dict(row) for row in EDITORIAL_CATEGORIES],
            "generator_available": False, "publication_enabled": False, "requires_human_review": True}


@router.get("/{import_id}")
def get_content_import(import_id: UUID) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM external_content_imports WHERE id=%s", (import_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Imported manuscript not found")
        events = conn.execute(
            "SELECT event_type,actor,reason,details,created_at FROM external_content_import_events WHERE import_id=%s ORDER BY created_at,id",
            (import_id,),
        ).fetchall()
        return {"item": dict(row), "events": [dict(event) for event in events], "publish_ready": False}


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
        exists = conn.execute("SELECT to_regclass('public.external_content_imports') AS relation").fetchone()
        if not exists or not exists.get("relation"):
            raise HTTPException(409, "Content import migration 045 is required")
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
        if not duplicate:
            details = {"external_content_id": request.item.content_id, "event_group_id": request.item.event_group_id,
                "language_code": request.item.language_code, "source_region": request.item.source_region,
                "category": request.item.category, "content_sha256": content_sha256,
                "reader_language_decisions": recommendations, "labels": labels,
                "source_fetch_performed": False, "provider_called": False, "blogger_write_performed": False,
                "publish_ready": False, "generation_ready": False}
            conn.execute(
                """INSERT INTO external_content_import_events(import_id,event_key,event_type,actor,reason,details)
                VALUES (%s,%s,'received',%s,%s,%s)""",
                (row["id"], f"import_{idempotency_key}", request.submitted_by,
                 "External manuscript accepted into the untrusted review queue; human source and claim review required.", Jsonb(details)),
            )
            conn.execute("INSERT INTO audit_events(event_type,payload) VALUES ('content.import.received',%s)", (Jsonb({"import_id": str(row["id"]), **details}),))
        return {"import_id": str(row["id"]), "state": row["state"], "duplicate": duplicate,
            "content_sha256": content_sha256, "category": request.item.category,
            "suggested_labels": labels, "reader_language_decisions": recommendations,
            "generation_ready": False, "publish_ready": False, "provider_called": False,
            "blogger_write_performed": False, "source_fetch_performed": False,
            "human_review_required": True}
