"""Authenticated research management. Every control is backed by durable state."""

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator

from . import collection, pipeline
from .ai import Draft, EngineFailure
from .db import connection
from .grounding import inspect
from .multilingual import Input
from .pipeline import required

router = APIRouter(prefix="/admin/research")


class Keyword(Input):
    profile_id: UUID
    category_id: UUID
    keyword: str = Field(min_length=2, max_length=150)
    search_intent: str = Field(min_length=3, max_length=500)
    collection_source: str = Field(min_length=3, max_length=500)
    rationale: str = Field(min_length=5, max_length=1000)
    expires_at: datetime
    priority: int = Field(default=50, ge=1, le=100)

    @field_validator("expires_at")
    @classmethod
    def future(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value <= datetime.now(UTC):
            raise ValueError("Future timezone-aware timestamp required")
        return value


class Selection(Input):
    status: Literal["selected", "excluded", "candidate"]


class Source(Input):
    keyword_id: UUID
    url: str = Field(max_length=2000)
    source_name: str = Field(min_length=2, max_length=200)
    source_language: str = Field(default="und", max_length=100)
    published_at: datetime | None = None
    evidence: str = Field(min_length=10, max_length=1000)
    reliability_reason: str = Field(min_length=10, max_length=1000)
    rights: str = Field(min_length=10, max_length=1000)
    access_policy: str = Field(min_length=10, max_length=1000)
    valid_until: datetime
    is_primary: bool = False

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Public HTTPS citation without credentials/query required")
        return value

    @field_validator("source_language")
    @classmethod
    def valid_source_language(cls, value: str) -> str:
        import langcodes

        if value != "und" and not langcodes.tag_is_valid(value):
            raise ValueError("Use a valid BCP 47 source language or und")
        return value if value == "und" else str(langcodes.standardize_tag(value))

    @field_validator("published_at", "valid_until")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Timezone required")
        return value


class Review(Input):
    approved: bool
    reason: str = Field(min_length=10, max_length=1000)
    reviewer: str = Field(min_length=2, max_length=100)
    source_language: str = Field(default="und", max_length=100)

    @field_validator("source_language")
    @classmethod
    def valid_review_language(cls, value: str) -> str:
        import langcodes

        if value != "und" and not langcodes.tag_is_valid(value):
            raise ValueError("Use a valid BCP 47 language tag or und")
        return value if value == "und" else str(langcodes.standardize_tag(value))


class LocalizeRequest(Input):
    fact_id: UUID
    target_language: str = Field(min_length=1, max_length=100)

    @field_validator("target_language")
    @classmethod
    def valid_target_language(cls, value: str) -> str:
        import langcodes

        if not langcodes.tag_is_valid(value):
            raise ValueError("Use a valid BCP 47 language tag")
        return str(langcodes.standardize_tag(value))


class Generate(Input):
    evaluation_only: bool = False
    keyword_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    profile_ids: list[UUID] | None = Field(default=None, max_length=50)


class ModelSettings(Input):
    engine: Literal["ollama", "llamacpp"] = "ollama"
    provider: Literal["mock", "local"] = "mock"
    model: str = Field(
        default="mock-v1", min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$"
    )
    enabled: bool = True
    language_verified: bool = False
    verification_reason: str = Field(default="", max_length=1000)
    prompt_id: UUID
    daily_limit: int = Field(default=5, ge=1, le=50)
    evaluation_daily_limit: int = Field(default=2, ge=0, le=50)
    threads: int = Field(default=2, ge=1, le=4)
    timeout_seconds: int = Field(default=30, ge=5, le=180)


class Prompt(Input):
    name: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    instructions: str = Field(min_length=30, max_length=5000)


class Controls(Input):
    paused: bool = False
    max_concurrency: int = Field(default=1, ge=1, le=2)
    cpu_percent: int = Field(default=80, ge=10, le=90)
    ram_percent: int = Field(default=80, ge=10, le=90)


class JobAction(Input):
    action: Literal["pause", "resume", "retry"]


class Schedule(Input):
    category_id: UUID
    profile_id: UUID
    active: bool = False
    schedule_cron: str = Field(default="0 9 * * *", max_length=100)
    timezone: str = Field(default="Asia/Seoul", max_length=100)
    quantity: int = Field(default=1, ge=1, le=10)


class CollectionRequest(Input):
    source_id: UUID
    profile_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    auto_generate: bool = False


class CollectionSchedule(Input):
    profile_id: UUID
    scheduled: bool = False
    interval_minutes: int = Field(default=60, ge=60, le=10080)
    auto_generate: bool = False


class ArticleHumanReview(Input):
    evaluation_id: UUID
    content_version_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    reviewer_name: str = Field(min_length=2, max_length=80)
    factual_accuracy: Literal["verified", "issue_found", "uncertain", "not_assessed"]
    translation_naturalness: Literal["acceptable", "issue_found", "uncertain", "not_assessed"]
    reader_value: Literal["useful", "insufficient", "uncertain", "not_assessed"]
    disposition: Literal["reviewed", "approved", "revision_requested", "rejected"]
    comments: str = Field(min_length=10, max_length=2000)
    requested_changes: str = Field(default="", max_length=2000)

    @field_validator("requested_changes")
    @classmethod
    def revision_requires_detail(cls, value: str, info: Any) -> str:
        if info.data.get("disposition") == "revision_requested" and len(value.strip()) < 10:
            raise ValueError("revision_requested_requires_change_details")
        if info.data.get("disposition") == "approved" and (
            info.data.get("factual_accuracy") != "verified"
            or info.data.get("translation_naturalness") != "acceptable"
            or info.data.get("reader_value") != "useful"
        ):
            raise ValueError("editorial_approval_requires_all_positive_review_checks")
        return value


@router.post("/collections", status_code=201)
def collect(request: CollectionRequest) -> dict[str, Any]:
    return collection.request(
        request.source_id, request.profile_id, request.idempotency_key, request.auto_generate
    )


@router.put("/collections/{source_id}")
def collection_schedule(source_id: UUID, request: CollectionSchedule) -> dict[str, Any]:
    with connection() as conn:
        return required(
            conn.execute(
                """UPDATE collection_sources SET profile_id=%s,scheduled=%s,
            interval_minutes=%s,auto_generate=%s,next_run_at=now() WHERE id=%s RETURNING *""",
                (
                    request.profile_id,
                    request.scheduled,
                    request.interval_minutes,
                    request.auto_generate,
                    source_id,
                ),
            ).fetchone()
        )


@router.get("/local-ai")
def local_status() -> dict[str, Any]:
    import json

    import httpx

    from .ai import EngineFailure
    from .local_inference import ROOT, auth_headers, runtime

    result: dict[str, Any] = {"available": False, "installed_models": []}
    folder = ROOT / ".local"
    if (folder / "manifest.json").exists():
        manifest = json.loads((folder / "manifest.json").read_text())
        result["installed_models"] = [
            {**m, "bytes": (folder / m["name"]).stat().st_size}
            for m in manifest["models"]
            if (folder / m["name"]).exists()
        ]
    try:
        info = runtime()
        with httpx.Client(timeout=2, trust_env=False, headers=auth_headers()) as client:
            result.update(
                available=client.get("http://127.0.0.1:11435/health").status_code == 200, **info
            )
    except (EngineFailure, httpx.HTTPError):
        pass
    return result


@router.get("/state")
def state() -> dict[str, Any]:
    from .external_policy import status as external_policy_status

    with connection() as conn:
        result: dict[str, Any] = {
            name: conn.execute(query).fetchall()
            for name, query in {
                "keywords": "SELECT k.*,p.language_code,p.target_country FROM keyword_candidates k JOIN language_profiles p ON p.id=k.profile_id ORDER BY k.collected_at DESC LIMIT 100",
                "sources": "SELECT s.*,r.approved,r.reason AS review_reason,r.reviewer,COALESCE(NULLIF(r.source_language,'und'),s.source_language) AS reviewed_source_language FROM research_sources s LEFT JOIN LATERAL (SELECT * FROM source_reviews WHERE source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true ORDER BY s.collected_at DESC LIMIT 100",
                "profiles": "SELECT p.*,l.display_name,l.active FROM language_profiles p JOIN languages l ON l.code=p.language_code ORDER BY p.language_code,p.target_country",
                "categories": "SELECT * FROM categories ORDER BY slug",
                "settings": "SELECT * FROM generation_settings ORDER BY profile_id",
                "prompts": "SELECT * FROM prompt_templates ORDER BY name,version DESC",
                "jobs": "SELECT r.*,j.keyword_id,j.paused FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id ORDER BY r.created_at DESC LIMIT 100",
                "attempts": "SELECT * FROM generation_attempts ORDER BY id DESC LIMIT 100",
                "versions": "SELECT v.*,g.run_id,g.profile_id,g.provider,g.model,g.prompt_id,g.state,g.result_metadata,g.source_snapshot,sa.checks AS latest_checks FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id LEFT JOIN LATERAL (SELECT checks FROM seo_audits WHERE content_version_id=v.id ORDER BY created_at DESC,id DESC LIMIT 1) sa ON true ORDER BY v.created_at DESC LIMIT 100",
                "schedules": "SELECT * FROM research_schedules ORDER BY next_run_at",
                "dispatches": "SELECT * FROM research_dispatches ORDER BY occurrence DESC LIMIT 100",
                "collection_sources": "SELECT * FROM collection_sources ORDER BY name",
                "collection_jobs": "SELECT r.*,j.source_id FROM job_runs r JOIN collection_jobs j ON j.run_id=r.id ORDER BY r.created_at DESC LIMIT 50",
                "measurements": "SELECT * FROM model_measurements ORDER BY created_at DESC LIMIT 50",
                "stage_runs": "SELECT * FROM generation_stage_runs ORDER BY started_at DESC LIMIT 300",
                "experiments": "SELECT * FROM research_experiment_evaluations ORDER BY created_at DESC LIMIT 200",
                "evidence_facts": "SELECT * FROM evidence_facts ORDER BY created_at DESC LIMIT 200",
                "localizations": "SELECT * FROM localization_evaluations ORDER BY created_at DESC LIMIT 200",
                "glossary": "SELECT * FROM glossary_entries ORDER BY target_language,source_term",
                "glossary_revisions": "SELECT * FROM glossary_entry_revisions ORDER BY id DESC LIMIT 200",
                "article_evaluations": "SELECT e.*,v.group_id,v.version,v.title AS saved_title,v.body AS saved_body FROM article_quality_evaluations e LEFT JOIN content_versions v ON v.id=e.content_version_id ORDER BY e.created_at DESC LIMIT 32",
            }.items()
        }
        result["coverage"] = conn.execute(
            """SELECT c.slug AS category,l.code AS language_code,
            coalesce((SELECT count(DISTINCT s.id) FROM language_profiles p
                JOIN keyword_candidates k ON k.profile_id=p.id AND k.category_id=c.id
                JOIN research_sources s ON s.keyword_id=k.id AND s.valid_until>now()
                JOIN LATERAL (SELECT approved FROM source_reviews WHERE source_id=s.id
                    ORDER BY review_sequence DESC LIMIT 1) review ON review.approved
                WHERE p.language_code=l.code AND k.status='selected'
                AND NOT EXISTS(SELECT 1 FROM research_sources newer WHERE newer.keyword_id=s.keyword_id
                    AND newer.url=s.url AND newer.revision>s.revision)),0) AS reviewed_source_count
            FROM categories c CROSS JOIN languages l WHERE l.active ORDER BY c.slug,l.code"""
        ).fetchall()
        result["cost_policy"] = external_policy_status()
        result["controls"] = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        result["worker"] = conn.execute(
            """SELECT service_name,process_id,status,last_error_category,last_seen_at,
                last_seen_at>now()-interval '45 seconds' AS fresh
            FROM worker_heartbeats WHERE service_name='research_worker'"""
        ).fetchone()
        result["evaluation_worker"] = conn.execute(
            """SELECT service_name,process_id,status,last_error_category,last_seen_at,
                last_seen_at>now()-interval '45 seconds' AS fresh
            FROM worker_heartbeats WHERE service_name='evaluation_worker'"""
        ).fetchone()
        result["daily_workload"] = conn.execute(
            """SELECT p.language_code,g.daily_limit AS operations_limit,
                g.evaluation_daily_limit AS evaluation_limit,
                count(*) FILTER (WHERE NOT j.evaluation_only)::int AS operations_used,
                count(*) FILTER (WHERE j.evaluation_only)::int AS evaluation_used,
                (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') + interval '1 day') AT TIME ZONE 'Asia/Seoul' AS resets_at
            FROM language_profiles p JOIN languages l ON l.code=p.language_code AND l.active
            JOIN generation_settings g ON g.profile_id=p.id
            LEFT JOIN generation_targets t ON t.profile_id=p.id
            LEFT JOIN generation_jobs j ON j.run_id=t.run_id AND j.created_at>=(date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')
            WHERE p.target_country=''
            GROUP BY p.language_code,g.daily_limit,g.evaluation_daily_limit ORDER BY p.language_code"""
        ).fetchall()
        result["operations_summary"] = {
            "jobs": conn.execute(
                "SELECT task_kind,status,count(*) AS count FROM job_runs GROUP BY task_kind,status ORDER BY task_kind,status"
            ).fetchall(),
            "content_states": conn.execute(
                "SELECT state,count(*) AS count FROM generation_results GROUP BY state ORDER BY state"
            ).fetchall(),
            "quality_evaluations": conn.execute(
                "SELECT status,count(*) AS count,sum((human_review_required)::int) AS human_review_pending FROM article_quality_evaluations GROUP BY status ORDER BY status"
            ).fetchall(),
            "recent_failures": conn.execute(
                "SELECT error_type,count(*) AS count,max(error_at) AS latest_at FROM job_runs WHERE status='failed' AND error_type IS NOT NULL GROUP BY error_type ORDER BY latest_at DESC LIMIT 20"
            ).fetchall(),
        }
        result["events"] = conn.execute(
            "SELECT id,run_id,event_type,payload,created_at FROM audit_events WHERE event_type LIKE 'research.%' ORDER BY id DESC LIMIT 100"
        ).fetchall()
        result["evaluation_results"] = _evaluation_results_snapshot()
        result["prepublication"] = _prepublication_snapshot(conn)
        result["adsense_readiness"] = _adsense_readiness_snapshot(
            conn, result["prepublication"]
        )
        result["article_reviews"] = conn.execute(
            """SELECT id,evaluation_id,content_version_id,idempotency_key,reviewer_name,
                factual_accuracy,translation_naturalness,reader_value,disposition,comments,
                requested_changes,created_at FROM article_human_reviews
                ORDER BY created_at DESC,id DESC LIMIT 100"""
        ).fetchall()
        result["operational_readiness"] = _operational_readiness_snapshot(conn, result)
        result["publishing_enabled"] = False
        result["paid_ai_enabled"] = False
        return result


def _evaluation_results_snapshot() -> dict[str, Any]:
    """Read evaluation-only drafts through the separate read-only database role."""
    from .config import settings

    url = settings().evaluation_database_url
    if not url:
        return {"configured": False, "runs": [], "stages": []}
    import psycopg
    from psycopg.rows import dict_row

    try:
        with psycopg.connect(url, connect_timeout=2, row_factory=dict_row) as conn:
            identity = conn.execute(
                "SELECT current_database() AS database_name"
            ).fetchone()
            snapshot = conn.execute(
                "SELECT min(created_at) AS snapshot_at FROM audit_events WHERE event_type='evaluation.environment.initialized'"
            ).fetchone()
            if not snapshot or not snapshot["snapshot_at"]:
                return {"configured": True, "available": False, "error_category": "evaluation_snapshot_marker_missing", "runs": [], "stages": [], "events": [], "quota": []}
            quota = conn.execute(
                """SELECT p.language_code,g.evaluation_daily_limit AS quota_limit,
                    count(*) FILTER (WHERE j.evaluation_only)::int AS quota_used,
                    (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') + interval '1 day') AT TIME ZONE 'Asia/Seoul' AS resets_at
                FROM language_profiles p JOIN languages l ON l.code=p.language_code AND l.active
                JOIN generation_settings g ON g.profile_id=p.id
                LEFT JOIN generation_targets t ON t.profile_id=p.id
                LEFT JOIN generation_jobs j ON j.run_id=t.run_id AND j.created_at >=
                    (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')
                WHERE p.target_country=''
                GROUP BY p.language_code,g.evaluation_daily_limit ORDER BY p.language_code"""
            ).fetchall()
            runs = conn.execute(
                """SELECT r.id AS run_id,r.status AS run_status,r.error_type,r.attempts,
                    r.created_at,j.evaluation_only,t.profile_id,g.state,g.provider,
                    COALESCE(g.model,t.settings_snapshot->>'model') AS model,
                    j.keyword_id,
                    g.elapsed_ms,g.result_metadata,g.source_snapshot,v.id AS version_id,
                    COALESCE(v.language,p.language_code) AS language_code,v.title,v.body,
                    EXISTS(SELECT 1 FROM research_sources s
                      JOIN LATERAL (SELECT approved FROM source_reviews WHERE source_id=s.id
                        ORDER BY review_sequence DESC LIMIT 1) review ON review.approved
                      WHERE s.keyword_id=j.keyword_id AND s.source_name LIKE 'SEC EDGAR%%'
                        AND s.valid_until>now()) AS sec_source,
                    EXISTS(SELECT 1 FROM research_sources s
                      JOIN LATERAL (SELECT approved FROM source_reviews WHERE source_id=s.id
                        ORDER BY review_sequence DESC LIMIT 1) review ON review.approved
                      WHERE s.keyword_id=j.keyword_id AND s.source_name LIKE 'Federal Reserve%%'
                        AND s.valid_until>now()) AS fed_source,false AS publish_ready
                FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
                JOIN generation_targets t ON t.run_id=r.id
                JOIN language_profiles p ON p.id=t.profile_id
                LEFT JOIN generation_results g ON g.run_id=r.id AND g.profile_id=t.profile_id
                LEFT JOIN content_versions v ON v.id=g.content_version_id
                WHERE j.evaluation_only AND r.created_at>%s
                ORDER BY r.created_at DESC,t.profile_id LIMIT 32""",
                (snapshot["snapshot_at"],),
            ).fetchall()
            fed_articles = _fed_article_reviews(conn)
            sec_history = conn.execute(
                """SELECT language_code,status,count(*)::int AS count,
                    max(created_at) AS latest_at
                FROM article_quality_evaluations
                WHERE topic ILIKE 'Apple Inc. 10-Q%'
                GROUP BY language_code,status ORDER BY language_code,status"""
            ).fetchall()
            sec_seed = conn.execute(
                """SELECT s.keyword_id,p.id AS profile_id
                FROM research_sources s
                JOIN LATERAL (SELECT approved FROM source_reviews WHERE source_id=s.id
                    ORDER BY review_sequence DESC LIMIT 1) review ON review.approved
                JOIN language_profiles p ON p.language_code='en' AND p.target_country=''
                WHERE s.source_name LIKE 'SEC EDGAR%%' AND s.valid_until>now()
                  AND NOT EXISTS(SELECT 1 FROM research_sources newer
                    WHERE newer.keyword_id=s.keyword_id AND newer.url=s.url AND newer.revision>s.revision)
                ORDER BY s.collected_at DESC LIMIT 1"""
            ).fetchone()
            sec_source_draft_available = False
            if sec_seed:
                sec_source_draft_available = bool(conn.execute(
                    """SELECT 1 FROM generation_results g
                    JOIN generation_jobs j ON j.run_id=g.run_id
                    JOIN job_runs r ON r.id=g.run_id
                    WHERE j.keyword_id=%s AND j.evaluation_only AND r.status='succeeded'
                      AND g.profile_id=%s AND g.content_version_id IS NOT NULL LIMIT 1""",
                    (sec_seed["keyword_id"], sec_seed["profile_id"]),
                ).fetchone())
            sec_locale_availability = _sec_locale_availability(
                quota, sec_source_draft_available
            )
            sec_reservation_active = bool(sec_seed and not sec_source_draft_available)
            for quota_row in quota:
                reserved = (
                    1 if quota_row["language_code"] == "en" and sec_reservation_active else 0
                )
                quota_row["reserved_slots"] = reserved
                quota_row["reserved_for"] = "SEC English source evaluation" if reserved else None
                quota_row["remaining_after_reservation"] = max(
                    0, int(quota_row["quota_limit"]) - int(quota_row["quota_used"]) - reserved
                )
            sec_gate = (
                "available_for_some_locales"
                if any(row["status"] == "available" for row in sec_locale_availability)
                else "blocked_source_locale_prerequisite"
                if sec_locale_availability and any(
                    row["status"] == "blocked_source_locale_prerequisite"
                    for row in sec_locale_availability
                )
                else "blocked_quota"
                if sec_locale_availability and all(
                    row["status"] == "blocked_quota" for row in sec_locale_availability
                )
                else "not_verified"
            )
            stages = conn.execute(
                """SELECT s.id,s.run_id,s.profile_id,s.stage_name,s.status,s.sequence,
                    s.model,s.elapsed_ms,s.error_category,s.source_ids,s.validation,
                    s.output_snapshot,s.started_at,s.finished_at
                FROM generation_stage_runs s JOIN generation_jobs j ON j.run_id=s.run_id
                WHERE j.evaluation_only AND s.started_at>%s ORDER BY s.started_at DESC LIMIT 160""",
                (snapshot["snapshot_at"],),
            ).fetchall()
            events = conn.execute(
                """SELECT id,run_id,event_type,payload,created_at FROM audit_events
                WHERE (event_type LIKE 'evaluation.%%' OR event_type LIKE 'generation.%%'
                    OR event_type LIKE 'stage.%%' OR event_type IN ('queued','started','completed','failed','retry','recovered','worker.status.changed'))
                  AND created_at>=%s
                ORDER BY id DESC LIMIT 160""",
                (snapshot["snapshot_at"],),
            ).fetchall()
            evaluation_worker = conn.execute(
                """SELECT service_name,process_id,status,last_error_category,last_seen_at,
                    last_seen_at>now()-interval '45 seconds' AS fresh
                FROM worker_heartbeats WHERE service_name='evaluation_worker'"""
            ).fetchone()
        return {
            "configured": True,
            "database": identity["database_name"] if identity else None,
            "baseline_snapshot_at": snapshot["snapshot_at"],
            "quota": quota,
            "sec_english_quota_reservation": {
                "active": sec_reservation_active,
                "slots": 1 if sec_reservation_active else 0,
                "reason": "reviewed SEC English source draft missing" if sec_reservation_active else "no pending SEC English source target",
            },
            "worker": evaluation_worker,
            "runs": runs,
            "sec_c3_runs": [
                run for run in runs
                if run.get("sec_source") or any(
                    isinstance(source, dict)
                    and str(source.get("source_name", "")).startswith("SEC EDGAR")
                    for source in (run.get("source_snapshot") or [])
                )
            ],
            "fed_articles": fed_articles,
            "sec_historical_quality": sec_history,
            "sec_new_inference": sec_gate,
            "sec_locale_availability": sec_locale_availability,
            "sec_source_draft_available": sec_source_draft_available,
            "stages": stages,
            "events": events,
            "publish_ready_forced_false": True,
        }
    except psycopg.Error as exc:
        # Never return a connection string, credentials, or raw driver error.
        return {"configured": True, "available": False, "error_category": "evaluation_read_failed", "error_code": exc.sqlstate, "runs": [], "stages": []}


def _adsense_readiness_snapshot(conn: Any, prepublication: dict[str, Any]) -> dict[str, Any]:
    """Report evidence-backed preparation checks; never infer or promise AdSense approval."""
    captured_at = conn.execute("SELECT now() AS captured_at").fetchone()["captured_at"]
    publication_counts = conn.execute(
        """SELECT blog_id,count(*)::int AS internal_published_records,
            max(published_at) AS last_internal_publish_at
        FROM publishing_records GROUP BY blog_id"""
    ).fetchall()
    counts = {str(row["blog_id"]): dict(row) for row in publication_counts}
    blogs: list[dict[str, Any]] = []
    checks = [
        ("public_published_posts", "Publicly published posts and current public post count", "not_verified"),
        ("originality_and_information_value", "Originality and information value", "human_review_required"),
        ("facts_and_sources", "Fact accuracy and source support", "human_review_required"),
        ("localization_quality", "Language-specific localization quality", "human_review_required"),
        ("article_structure", "Titles, headings, and readable article structure", "human_review_required"),
        ("copyright_and_quotes", "Copyright, reuse rights, and quotation review", "human_review_required"),
        ("about_page", "About page", "not_verified"),
        ("contact_page", "Contact page", "not_verified"),
        ("privacy_policy", "Privacy policy", "not_verified"),
        ("search_console", "Search Console property and ownership", "not_verified"),
        ("sitemap", "Sitemap accessibility and Search Console status", "not_verified"),
        ("mobile_readability", "Mobile readability", "not_verified"),
        ("broken_links", "Broken links and navigation", "not_verified"),
        ("policy_risk", "Potential AdSense policy issues", "human_review_required"),
    ]
    for blog in prepublication.get("blogs", []):
        blog_id = str(blog["id"])
        internal = counts.get(blog_id, {})
        items: list[dict[str, Any]] = [
            {
                "key": key,
                "label": label,
                "status": status,
                "evidence": {
                    "public_fetch_performed": False,
                    "blogger_read_cost_gate": "provider_cost_unverified",
                    "reason": "No public Blogger/API inspection was performed; this field must not be inferred from internal drafts.",
                },
            }
            for key, label, status in checks
        ]
        items[0]["evidence"]["public_post_count"] = None
        items[0]["evidence"]["internal_publication_records"] = int(
            internal.get("internal_published_records", 0)
        )
        items[0]["evidence"]["last_internal_publish_at"] = internal.get(
            "last_internal_publish_at"
        )
        blogs.append({
            "blog_id": blog.get("blog_id"),
            "blog_mapping_id": blog_id,
            "language_code": blog.get("language_code"),
            "url": blog.get("url"),
            "display_name": blog.get("display_name"),
            "active": blog.get("active"),
            "captured_at": captured_at,
            "checks": items,
            "approval_prediction": "not_provided",
        })
    return {
        "captured_at": captured_at,
        "approval_prediction": "not_provided",
        "blogs": blogs,
        "internal_recommendations": {
            "suggested_published_post_count": "15-20 (internal planning heuristic only; not a Google requirement)",
            "suggested_article_length": "1000-1500 characters (internal planning heuristic only; not a Google requirement)",
            "used_as_approval_gate": False,
        },
        "official_references": [
            "https://support.google.com/adsense/answer/7299563",
            "https://support.google.com/adsense/answer/9724",
            "https://support.google.com/adsense/answer/12176698",
            "https://support.google.com/webmasters/answer/7451001",
        ],
    }


def _fed_article_reviews(conn: Any) -> list[dict[str, Any]]:
    """Read the four latest machine-passed Fed C3 drafts from the isolated DB."""
    rows = conn.execute(
        """SELECT DISTINCT ON (q.language_code) q.id AS evaluation_id,
            q.content_version_id,q.language_code,q.topic,q.title,q.summary,q.keywords,
            q.source_ids,q.fact_ids,q.model,q.prompt_version,q.metrics,q.checks,
            q.machine_passed,q.human_review_required,q.status,q.created_at,
            v.body,v.version AS content_version
        FROM article_quality_evaluations q
        JOIN content_versions v ON v.id=q.content_version_id
        WHERE q.topic_key LIKE 'phase39t:%%' AND q.topic ILIKE 'Federal Reserve%%'
          AND q.machine_passed AND q.human_review_required AND NOT q.publish_ready
          AND q.content_version_id IS NOT NULL
        ORDER BY q.language_code,q.created_at DESC,q.id DESC"""
    ).fetchall()
    articles: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        source_ids = item["source_ids"]
        fact_ids = item["fact_ids"]
        sources = conn.execute(
            """SELECT id,source_name,url,published_at,collected_at,evidence,rights,
                access_policy,valid_until,revision,source_language
            FROM research_sources WHERE id=ANY(%s) ORDER BY id""",
            (source_ids,),
        ).fetchall()
        facts = conn.execute(
            """SELECT id,fact_key,source_id,source_language,source_excerpt,entity_ids,
                numeric_values,date_values,citation_ids,verification_status
            FROM evidence_facts WHERE id=ANY(%s) ORDER BY fact_key,id""",
            (fact_ids,),
        ).fetchall()
        item["sources"] = [dict(source) for source in sources]
        item["facts"] = [dict(fact) for fact in facts]
        check_payload = item.get("checks") or {}
        check_payload = check_payload.get("checks", check_payload) if isinstance(check_payload, dict) else {}
        grounding_details = check_payload.get("grounding_details", {}) if isinstance(check_payload, dict) else {}
        item["proper_name_candidates"] = (
            grounding_details.get("proper_name_candidates", [])
            if isinstance(grounding_details, dict) else []
        )
        item["publication_approval_granted"] = False
        item["publish_ready"] = False
        articles.append(item)
    return articles


def _prepublication_snapshot(conn: Any) -> dict[str, Any]:
    blogs = conn.execute(
        """SELECT b.id,b.language_code,b.url,b.blog_id,b.active,
            b.connection_verified_at,b.last_checked_at,b.connection_error,
            g.status AS oauth_status,g.scopes
        FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        ORDER BY b.language_code,b.url"""
    ).fetchall()
    safety = conn.execute(
        """SELECT
            (SELECT count(*)::int FROM publishing_jobs WHERE NOT simulation_only OR adapter_type<>'fake') AS non_mock_jobs,
            (SELECT count(*)::int FROM publishing_records) AS real_publishing_records,
            (SELECT count(*)::int FROM article_quality_evaluations WHERE publish_ready) AS publish_ready_evaluations,
            (SELECT count(*)::int FROM publishing_policies WHERE auto_publish_allowed) AS auto_publish_policies,
            EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_proc p ON p.oid=t.tgfoid
                WHERE c.relname='audit_events' AND p.proname='deny_mutation' AND t.tgenabled='O') AS audit_immutable"""
    ).fetchone()
    blog_ids = [blog["id"] for blog in blogs]
    verification_events = (
        conn.execute(
            """SELECT DISTINCT ON (blog_id) blog_id,payload,created_at
            FROM audit_events WHERE event_type='blogger.verification.completed'
              AND blog_id=ANY(%s) ORDER BY blog_id,created_at DESC,id DESC""",
            (blog_ids,),
        ).fetchall()
        if blog_ids else []
    )
    return {
        "blogger_accounts_connected": conn.execute(
            "SELECT count(*)::int AS n FROM google_connections WHERE status='connected'"
        ).fetchone()["n"],
        "blogs": [dict(blog) for blog in blogs],
        "historical_read_verifications": [dict(event) for event in verification_events],
        "safety": dict(safety),
        "real_blogger_sync_verified": False,
        "real_writes_enabled": False,
    }


def _sec_locale_availability(
    quota: list[dict[str, Any]], source_draft_available: bool
) -> list[dict[str, Any]]:
    """Apply per-language quota and the pipeline's English source-draft dependency."""
    results: list[dict[str, Any]] = []
    for row in quota:
        language = str(row["language_code"])
        limit = int(row["quota_limit"])
        used = int(row["quota_used"])
        remaining = max(0, limit - used)
        if remaining == 0:
            status = "blocked_quota"
        elif language != "en" and not source_draft_available:
            status = "blocked_source_locale_prerequisite"
        else:
            status = "available"
        results.append({
            "language_code": language,
            "quota_limit": limit,
            "quota_used": used,
            "quota_remaining": remaining,
            "source_locale_prerequisite": "en" if language != "en" else None,
            "source_draft_available": source_draft_available if language != "en" else None,
            "status": status,
        })
    return results


def _operational_readiness_snapshot(conn: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Build a fail-closed checklist from current DB/API state and cited test artifacts."""
    evaluation = state.get("evaluation_results") or {}
    fed = evaluation.get("fed_articles") or []
    expected_fed_languages = {
        str(profile.get("language_code")) for profile in (state.get("profiles") or [])
        if profile.get("active") and not profile.get("target_country")
    }
    if not expected_fed_languages:
        expected_fed_languages = {str(article.get("language_code")) for article in fed}
    passed_fed_languages = {
        str(article.get("language_code")) for article in fed if article.get("machine_passed")
    }
    reviews = state.get("article_reviews") or []
    latest_reviews: dict[str, dict[str, Any]] = {}
    for review in reviews:
        latest_reviews.setdefault(str(review.get("evaluation_id")), review)
    fed_reviewed = sum(
        1 for article in fed
        if str(article.get("evaluation_id")) in latest_reviews
    )
    fed_review_approved = sum(
        1 for article in fed
        if (review := latest_reviews.get(str(article.get("evaluation_id"))))
        and review.get("disposition") == "approved"
        and review.get("factual_accuracy") == "verified"
        and review.get("translation_naturalness") == "acceptable"
        and review.get("reader_value") == "useful"
    )
    sec_runs = evaluation.get("sec_c3_runs") or []
    sec_drafts = [run for run in sec_runs if run.get("version_id") and run.get("body")]
    sec_machine_passed = 0
    for run in sec_runs:
        metadata = run.get("result_metadata") or {}
        quality = metadata.get("quality") or {}
        grounding = quality.get("grounding") or {}
        if run.get("run_status") == "succeeded" and quality.get("structural_pass") and grounding.get("rule_pass") and quality.get("localization_pass", True):
            sec_machine_passed += 1

    cost_policy = state.get("cost_policy") or {}
    blogger_provider: dict[str, Any] = next(
        (item for item in cost_policy.get("providers", []) if item.get("name") == "google_blogger_read"),
        {},
    )
    blogs = (state.get("prepublication") or {}).get("blogs") or []
    mapped_readonly = sum(
        1 for blog in blogs
        if blog.get("active") and blog.get("url")
        and blog.get("blog_id") and blog.get("oauth_status") == "connected"
        and "https://www.googleapis.com/auth/blogger.readonly" in (blog.get("scopes") or [])
    )
    mock = conn.execute(
        """SELECT count(*) FILTER (WHERE adapter_type='fake')::int AS attempts,
            count(*) FILTER (WHERE adapter_type<>'fake')::int AS non_mock_attempts,
            count(*) FILTER (WHERE adapter_type='fake' AND outcome='succeeded')::int AS mock_successes,
            count(*) FILTER (WHERE adapter_type='fake' AND outcome<>'succeeded')::int AS mock_non_successes,
            max(created_at) FILTER (WHERE adapter_type='fake') AS latest_attempt_at
        FROM publication_attempts"""
    ).fetchone()

    worker_evidence = _worker_recovery_evidence()
    safety = (state.get("prepublication") or {}).get("safety") or {}
    items = [
        {"key": "fed_machine", "status": "passed" if expected_fed_languages and expected_fed_languages.issubset(passed_fed_languages) else "incomplete", "evidence": f"{len(expected_fed_languages & passed_fed_languages)}/{len(expected_fed_languages)} active base-profile languages have a current machine-passed Fed draft"},
        {"key": "fed_human", "status": "not_available" if not fed else "pending" if fed_reviewed < len(fed) else "editorially_approved" if fed_review_approved == len(fed) else "reviewed_not_approved", "evidence": f"{fed_reviewed}/{len(fed)} reviewed; {fed_review_approved}/{len(fed)} explicitly approved for editorial quality; review records={len(reviews)}"},
        {"key": "sec_machine", "status": "passed" if sec_runs and sec_machine_passed == len(sec_runs) else "partially_passed" if sec_machine_passed else "failed_before_draft" if sec_runs else evaluation.get("sec_new_inference", "not_verified"), "evidence": {"new_sec_c3_attempts": len(sec_runs), "drafts_saved": len(sec_drafts), "machine_passed": sec_machine_passed, "failures": [{"language": run.get("language_code"), "status": run.get("run_status"), "error": run.get("error_type")} for run in sec_runs if run.get("run_status") != "succeeded"], "historical_evaluations_separate": True, "locale_availability": evaluation.get("sec_locale_availability", [])}},
        {"key": "sec_human", "status": "not_available" if not sec_drafts else "pending", "evidence": f"new SEC C3 saved drafts requiring review={len(sec_drafts)}; attempts without a saved draft are not review items"},
        {"key": "blogger_cost", "status": "blocked_provider_cost_unverified" if blogger_provider.get("block_reason") == "manual_zero_cost_review_required" else "allowed" if blogger_provider.get("calls_allowed") else "blocked", "evidence": f"provider calls_allowed={bool(blogger_provider.get('calls_allowed'))}; reason={blogger_provider.get('block_reason') or 'none'}"},
        {"key": "blogger_read_connection", "status": "configured_live_read_blocked" if mapped_readonly == len(blogs) and mapped_readonly > 0 and not (state.get("prepublication") or {}).get("real_blogger_sync_verified") else "incomplete", "evidence": f"readonly DB mappings={mapped_readonly}/{len(blogs)}; live GET is independently gated by cost policy"},
        {"key": "publication_mock", "status": "verified_historical" if mock["attempts"] > 0 and mock["non_mock_attempts"] == 0 else "not_verified", "evidence": {"fake_attempts": mock["attempts"], "mock_successes": mock["mock_successes"], "mock_non_successes": mock["mock_non_successes"], "non_mock_attempts": mock["non_mock_attempts"], "captured_at": mock.get("latest_attempt_at"), "scope": "historical mock evidence; not a live readiness claim"}},
        {"key": "worker_recovery", "status": "verified_historical" if worker_evidence.get("passed") else "not_verified", "evidence": worker_evidence},
        {"key": "operating_write_block", "status": "blocked_safe" if not (state.get("prepublication") or {}).get("real_writes_enabled") and safety.get("non_mock_jobs") == 0 and safety.get("real_publishing_records") == 0 else "needs_investigation", "evidence": {"real_writes_enabled": False, "non_mock_jobs": safety.get("non_mock_jobs"), "real_publishing_records": safety.get("real_publishing_records"), "publish_ready_evaluations": safety.get("publish_ready_evaluations")}},
        {"key": "additional_cost_block", "status": "policy_active" if not cost_policy.get("blocked_credential_names") else "blocked_credentials_detected", "evidence": {"blocked_credential_names": cost_policy.get("blocked_credential_names", []), "paid_provider_allowlist_entries": 0}},
        {"key": "separate_live_publication_approval", "status": "required_not_granted", "evidence": {"publishing_enabled": False, "publish_ready": False}},
    ]
    return {"captured_from": "current operations DB and isolated evaluation DB snapshot", "items": items}


def _worker_recovery_evidence() -> dict[str, Any]:
    """Summarize immutable, historical isolated-worker test artifacts without changing them."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    artifacts = sorted((root / "docs" / "development").glob("P3-9S-worker-*.json"))
    valid: list[tuple[str, str]] = []
    for artifact in artifacts:
        try:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            jobs = payload.get("jobs") or {}
            abrupt = payload.get("abrupt_worker") or {}
            restart = abrupt.get("restart") or {}
            passed = (
                payload.get("kind") == "isolated_worker_real_process"
                and (payload.get("normal_worker") or {}).get("exit_code") == 0
                and jobs.get("normal") == "succeeded_once"
                and jobs.get("lease_expired_attempt_1") == "recovered_and_succeeded_attempt_2"
                and jobs.get("duplicate_idempotency_rows") == 1
                and restart.get("exit_code") == 0
                and abrupt.get("final_status") == "stopped"
                and payload.get("operational_public_schema_rows_for_test_keys") == 0
            )
            if passed:
                valid.append((str(payload.get("captured_at", "")), artifact.name))
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    latest = max(valid, default=None)
    return {"passed": latest is not None, "artifact_count": len(valid), "latest_artifact": latest[1] if latest else None, "captured_at": latest[0] if latest else None, "scope": "historical isolated test; not a live worker health claim"}


@router.post("/article-reviews", status_code=201)
def record_article_review(request: ArticleHumanReview) -> dict[str, Any]:
    """Append a human content review note; never approves Blogger publication."""
    from psycopg.types.json import Jsonb

    from .config import settings

    url = settings().evaluation_database_url
    if not url:
        raise HTTPException(503, "Isolated evaluation review data is unavailable")
    import psycopg
    from psycopg.rows import dict_row

    try:
        with psycopg.connect(url, connect_timeout=2, row_factory=dict_row) as evaluation_conn:
            db = evaluation_conn.execute("SELECT current_database() AS name").fetchone()
            if not db or db["name"] != "woori_blog_agent_eval":
                raise HTTPException(503, "Evaluation database identity check failed")
            valid = evaluation_conn.execute(
                """SELECT 1 FROM article_quality_evaluations q
                JOIN content_versions v ON v.id=q.content_version_id
                WHERE q.id=%s AND q.content_version_id=%s
                  AND q.topic_key LIKE 'phase39t:%%' AND q.topic ILIKE 'Federal Reserve%%'
                  AND q.machine_passed AND q.human_review_required AND NOT q.publish_ready""",
                (request.evaluation_id, request.content_version_id),
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(503, "Evaluation review data is unavailable") from exc
    if not valid:
        raise HTTPException(404, "Review target is not an eligible Fed evaluation draft")

    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM article_human_reviews WHERE idempotency_key=%s",
            (request.idempotency_key,),
        ).fetchone()
        if existing:
            return {"review": dict(existing), "duplicate": True, "publication_approval_granted": False}
        row = conn.execute(
            """INSERT INTO article_human_reviews(evaluation_id,content_version_id,idempotency_key,
                reviewer_name,factual_accuracy,translation_naturalness,reader_value,disposition,
                comments,requested_changes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (request.evaluation_id,request.content_version_id,request.idempotency_key,
             request.reviewer_name,request.factual_accuracy,request.translation_naturalness,
             request.reader_value,request.disposition,request.comments,request.requested_changes),
        ).fetchone()
        if row is None:
            existing = conn.execute(
                "SELECT * FROM article_human_reviews WHERE idempotency_key=%s",
                (request.idempotency_key,),
            ).fetchone()
            if existing is None:
                raise HTTPException(409, "Review idempotency conflict")
            return {"review": dict(existing), "duplicate": True, "publication_approval_granted": False}
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('article.human_review.recorded',%s)",
            (Jsonb({"review_id": str(row["id"]), "evaluation_id": str(request.evaluation_id),
                "content_version_id": str(request.content_version_id),
                "disposition": request.disposition, "publication_approval_granted": False,
                "publish_ready": False}),),
        )
        return {"review": dict(row), "duplicate": False, "publication_approval_granted": False,
            "publish_ready": False, "content_version_changed": False}


@router.post("/versions/{version_id}/validate")
def revalidate(version_id: UUID) -> dict[str, Any]:
    from psycopg.types.json import Jsonb

    with connection() as conn:
        row = required(
            conn.execute(
                """SELECT v.*,g.profile_id,g.run_id,g.result_metadata,g.source_snapshot,j.keyword_id
            FROM content_versions v JOIN generation_results g ON g.content_version_id=v.id
            JOIN generation_jobs j ON j.run_id=g.run_id WHERE v.id=%s""",
                (version_id,),
            ).fetchone()
        )
    metadata = row["result_metadata"]
    source_ids = metadata.get(
        "referenced_source_ids", [str(s["id"]) for s in row["source_snapshot"]]
    )
    draft = Draft(
        title=row["title"],
        body=row["body"],
        summary=metadata["summary"],
        keywords=metadata["keywords"],
        source_ids=source_ids,
    )
    checks = inspect(
        draft, row["source_snapshot"], row["language"], datetime.now(UTC).date().isoformat()
    )
    try:
        current = pipeline.evidence(row["keyword_id"])
        checks["input_revision_current"] = {str(s["id"]) for s in current} == {
            str(s["id"]) for s in row["source_snapshot"]
        }
    except EngineFailure:
        checks["input_revision_current"] = False
    checks["rule_pass"] = bool(checks["rule_pass"] and checks["input_revision_current"])
    with connection() as conn:
        conn.execute(
            "INSERT INTO seo_audits(content_version_id,profile_id,passed,validator_adapter,checks) VALUES (%s,%s,%s,'grounding-v3-phase38a',%s)",
            (version_id, row["profile_id"], checks["rule_pass"], Jsonb(checks)),
        )
        pipeline.emit(
            conn, "quality.rechecked", row["run_id"], version_id=str(version_id), checks=checks
        )
    return checks


@router.post("/keywords", status_code=201)
def add_keyword(request: Keyword) -> dict[str, Any]:
    with connection() as conn:
        active = conn.execute(
            "SELECT l.active FROM language_profiles p JOIN languages l ON l.code=p.language_code WHERE p.id=%s",
            (request.profile_id,),
        ).fetchone()
        if not active or not active["active"]:
            raise HTTPException(409, "Active language profile required")
        row = conn.execute(
            """INSERT INTO keyword_candidates(profile_id,category_id,keyword,normalized_keyword,search_intent,collection_source,rationale,expires_at,priority)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(profile_id,normalized_keyword) DO NOTHING RETURNING *""",
            (
                request.profile_id,
                request.category_id,
                request.keyword,
                pipeline.normalized(request.keyword),
                request.search_intent,
                request.collection_source,
                request.rationale,
                request.expires_at,
                request.priority,
            ),
        ).fetchone()
        if not row:
            raise HTTPException(409, "Duplicate keyword")
        return row


@router.put("/keywords/{keyword_id}")
def select_keyword(keyword_id: UUID, request: Selection) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            "UPDATE keyword_candidates SET status=%s WHERE id=%s RETURNING *",
            (request.status, keyword_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Keyword not found")
        return row


@router.post("/sources", status_code=201)
def add_source(request: Source) -> dict[str, Any]:
    if request.valid_until <= datetime.now(UTC) or (
        request.published_at and request.published_at > datetime.now(UTC)
    ):
        raise HTTPException(422, "Invalid source dates")
    values = request.model_dump()
    columns = list(values)
    with connection() as conn:
        return required(
            conn.execute(
                "INSERT INTO research_sources("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join(["%s"] * len(columns))
                + ") RETURNING *",
                tuple(values.values()),
            ).fetchone()
        )


@router.post("/sources/{source_id}/reviews", status_code=201)
def review_source(source_id: UUID, request: Review) -> dict[str, Any]:
    with connection() as conn:
        return required(
            conn.execute(
                "INSERT INTO source_reviews(source_id,approved,reason,reviewer,source_language) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (
                    source_id,
                    request.approved,
                    request.reason,
                    request.reviewer,
                    request.source_language,
                ),
            ).fetchone()
        )


@router.post("/sources/{source_id}/facts", status_code=201)
def extract_source_facts(source_id: UUID) -> dict[str, Any]:
    from psycopg.types.json import Jsonb

    from .localization import fact_ledger

    with connection() as conn:
        source = conn.execute(
            """SELECT s.*,COALESCE(NULLIF(r.source_language,'und'),s.source_language) AS reviewed_source_language
            FROM research_sources s
            JOIN LATERAL (SELECT approved,source_language FROM source_reviews WHERE source_id=s.id
              ORDER BY review_sequence DESC LIMIT 1) r ON r.approved
            WHERE s.id=%s AND s.valid_until>now()
            AND NOT EXISTS(SELECT 1 FROM research_sources n WHERE n.keyword_id=s.keyword_id
              AND n.url=s.url AND n.revision>s.revision)""",
            (source_id,),
        ).fetchone()
        if source is None:
            raise HTTPException(409, "Current, unexpired, reviewed source required")
        source = dict(source)
        source["source_language"] = source["reviewed_source_language"]
        stored = []
        for fact in fact_ledger(source):
            row = conn.execute(
                """INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,
                entity_ids,numeric_values,date_values,citation_ids,verification_status,extractor_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(source_id,fact_key,extractor_version) DO NOTHING RETURNING *""",
                (
                    fact["fact_key"],
                    source_id,
                    fact["source_language"],
                    fact["source_excerpt"],
                    fact["entity_ids"],
                    Jsonb(fact["numeric_values"]),
                    Jsonb(fact["date_values"]),
                    [source_id],
                    fact["verification_status"],
                    fact["extractor_version"],
                ),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM evidence_facts WHERE source_id=%s AND fact_key=%s AND extractor_version=%s",
                    (source_id, fact["fact_key"], fact["extractor_version"]),
                ).fetchone()
            stored.append(row)
        pipeline.emit(
            conn,
            "research.evidence_facts.extracted",
            None,
            source_id=str(source_id),
            fact_count=len(stored),
        )
        return {"source_id": source_id, "facts": stored, "human_review_required": True}


@router.post("/localizations", status_code=201)
def localize_evidence(request: LocalizeRequest) -> dict[str, Any]:
    from psycopg.types.json import Jsonb

    from .localization import localize_fact

    with connection() as conn:
        fact = conn.execute(
            """SELECT f.*,s.url AS source_url,s.source_name,s.valid_until,
            (SELECT approved FROM source_reviews r WHERE r.source_id=s.id
              ORDER BY r.review_sequence DESC LIMIT 1) AS source_approved,
            NOT EXISTS(SELECT 1 FROM research_sources n WHERE n.keyword_id=s.keyword_id
              AND n.url=s.url AND n.revision>s.revision) AS is_current
            FROM evidence_facts f JOIN research_sources s ON s.id=f.source_id WHERE f.id=%s""",
            (request.fact_id,),
        ).fetchone()
        language = conn.execute(
            "SELECT code,active FROM languages WHERE code=%s", (request.target_language,)
        ).fetchone()
        profile = conn.execute(
            """SELECT p.id,g.provider,g.model,g.timeout_seconds,g.enabled,g.language_verified,g.daily_limit,
            c.translation_supported FROM language_profiles p
            JOIN generation_settings g ON g.profile_id=p.id
            JOIN language_capabilities c ON c.profile_id=p.id
            WHERE p.language_code=%s ORDER BY p.target_country LIMIT 1""",
            (request.target_language,),
        ).fetchone()
        if fact is None or language is None or not language["active"] or profile is None:
            raise HTTPException(404, "Fact or active language profile not found")
        if (
            fact["verification_status"] != "source_span_verified"
            or not fact["source_approved"]
            or not fact["is_current"]
            or fact["valid_until"] <= datetime.now(UTC)
        ):
            raise HTTPException(409, "Verified source-span fact required")
        glossary = conn.execute(
            """SELECT source_term,localized_term,source_language,target_language,
            official_translation,translation_source,approved FROM glossary_entries
            WHERE profile_id=%s""",
            (profile["id"],),
        ).fetchall()
        localization_count = required(
            conn.execute(
                """SELECT count(*) AS count FROM localization_evaluations
            WHERE target_language=%s AND created_at>=date_trunc('day',now())""",
                (request.target_language,),
            ).fetchone()
        )["count"]
        if localization_count >= profile["daily_limit"]:
            raise HTTPException(429, "Daily localization limit reached; no fallback or retry")
    model_name = "deterministic-same-language"
    if fact["source_language"] == request.target_language:
        result = localize_fact(fact, request.target_language, glossary=glossary)
    elif (
        profile["provider"] != "local"
        or not profile["enabled"]
        or not profile["language_verified"]
        or not profile["translation_supported"]
    ):
        result = {
            "text": fact["source_excerpt"],
            "source_language": fact["source_language"],
            "target_language": request.target_language,
            "fact_id": fact["fact_key"],
            "source_ids": [str(fact["source_id"])],
            "status": "held_translation_language_unverified",
            "checks": {"translation_supported_and_verified": False},
            "ai_calls": 0,
            "human_review_required": True,
            "publish_ready": False,
        }
    else:
        from .ai import EngineFailure
        from .local_inference import localized_translation

        model_name = profile["model"]
        translator = lambda excerpt, target, terms, entities: localized_translation(
            excerpt, target, terms, entities, profile["model"], profile["timeout_seconds"]
        )
        try:
            result = localize_fact(fact, request.target_language, translator, glossary)
        except EngineFailure as error:
            result = {
                "text": "",
                "source_language": fact["source_language"],
                "target_language": request.target_language,
                "fact_id": fact["fact_key"],
                "source_ids": [str(fact["source_id"])],
                "status": "held_" + error.category,
                "checks": {"translation_completed": False},
                "ai_calls": 1,
                "human_review_required": True,
                "publish_ready": False,
            }
        except Exception:  # noqa: BLE001 - persist a sanitized hold; never expose model errors.
            result = {
                "text": "",
                "source_language": fact["source_language"],
                "target_language": request.target_language,
                "fact_id": fact["fact_key"],
                "source_ids": [str(fact["source_id"])],
                "status": "held_localization_failed",
                "checks": {"translation_completed": False},
                "ai_calls": 1,
                "human_review_required": True,
                "publish_ready": False,
            }
    metrics = {
        "elapsed_ms": result.get("elapsed_ms"),
        "ai_calls": result.get("ai_calls", 0),
        "model": model_name,
    }
    with connection() as conn:
        row = required(
            conn.execute(
                """INSERT INTO localization_evaluations(source_id,fact_id,target_language,output_snapshot,
            metrics,checks,machine_passed,human_review_required,publish_ready)
            VALUES (%s,%s,%s,%s,%s,%s,%s,true,false) RETURNING *""",
                (
                    fact["source_id"],
                    request.fact_id,
                    request.target_language,
                    Jsonb(result),
                    Jsonb(metrics),
                    Jsonb(result.get("checks", {})),
                    result.get("status") == "machine_passed",
                ),
            ).fetchone()
        )
        pipeline.emit(
            conn,
            "research.localization.completed",
            None,
            evaluation_id=str(row["id"]),
            fact_id=str(request.fact_id),
            language=request.target_language,
            status=result.get("status"),
            ai_calls=result.get("ai_calls", 0),
        )
        return row


@router.post("/jobs", status_code=201)
def generate(request: Generate) -> dict[str, Any]:
    return pipeline.enqueue(
        request.keyword_id, request.idempotency_key, request.profile_ids, request.evaluation_only
    )


@router.post("/jobs/{run_id}/action")
def job_action(run_id: UUID, request: JobAction) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            "SELECT r.* FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id WHERE r.id=%s FOR UPDATE OF r,j",
            (run_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Generation job not found")
        if request.action == "retry":
            if row["status"] != "failed" or row["attempts"] >= 3:
                raise HTTPException(409, "Only failed jobs below three attempts can retry")
            conn.execute(
                "UPDATE job_runs SET status='queued',available_at=now(),updated_at=now() WHERE id=%s",
                (run_id,),
            )
        conn.execute(
            "UPDATE generation_jobs SET paused=%s WHERE run_id=%s",
            (request.action == "pause", run_id),
        )
        pipeline.emit(conn, "job." + request.action, run_id)
        return {"id": run_id, "action": request.action}


@router.put("/settings/{profile_id}")
def settings(profile_id: UUID, request: ModelSettings) -> dict[str, Any]:
    if request.language_verified and len(request.verification_reason.strip()) < 10:
        raise HTTPException(422, "Language/model evaluation evidence required")
    fields = request.model_dump()
    with connection() as conn:
        row = conn.execute(
            "UPDATE generation_settings SET "
            + ",".join(k + "=%s" for k in fields)
            + " WHERE profile_id=%s RETURNING *",
            (*fields.values(), profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Profile not found")
        return row


@router.post("/prompts", status_code=201)
def add_prompt(request: Prompt) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781206)")
        return required(
            conn.execute(
                """INSERT INTO prompt_templates(name,version,instructions)
            SELECT %s,coalesce(max(version),0)+1,%s FROM prompt_templates WHERE name=%s RETURNING *""",
                (request.name, request.instructions, request.name),
            ).fetchone()
        )


@router.put("/controls")
def controls(request: Controls) -> dict[str, Any]:
    with connection() as conn:
        return required(
            conn.execute(
                "UPDATE pipeline_controls SET paused=%s,max_concurrency=%s,cpu_percent=%s,ram_percent=%s RETURNING *",
                (request.paused, request.max_concurrency, request.cpu_percent, request.ram_percent),
            ).fetchone()
        )


@router.post("/schedules", status_code=201)
def schedule(request: Schedule) -> dict[str, Any]:
    try:
        now = datetime.now(ZoneInfo(request.timezone))
        iterator = croniter(request.schedule_cron, now)
        first = iterator.get_next(datetime)
        if (iterator.get_next(datetime) - first).total_seconds() < 300:
            raise ValueError("Minimum interval is five minutes")
    except (ValueError, KeyError, ZoneInfoNotFoundError):
        raise HTTPException(422, "Invalid cron/timezone or interval below five minutes") from None
    with connection() as conn:
        return required(
            conn.execute(
                """INSERT INTO research_schedules(category_id,profile_id,active,schedule_cron,timezone,quantity,next_run_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(category_id,profile_id) DO UPDATE SET active=EXCLUDED.active,
            schedule_cron=EXCLUDED.schedule_cron,timezone=EXCLUDED.timezone,quantity=EXCLUDED.quantity,next_run_at=EXCLUDED.next_run_at RETURNING *""",
                (
                    request.category_id,
                    request.profile_id,
                    request.active,
                    request.schedule_cron,
                    request.timezone,
                    request.quantity,
                    first,
                ),
            ).fetchone()
        )
