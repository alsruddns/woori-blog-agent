"""Authenticated research management. Every control is backed by durable state."""

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator

from . import pipeline
from .db import connection
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


class Generate(Input):
    keyword_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    profile_ids: list[UUID] | None = Field(default=None, max_length=50)


class ModelSettings(Input):
    provider: Literal["mock", "local"] = "mock"
    model: str = Field(
        default="mock-v1", min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$"
    )
    enabled: bool = True
    language_verified: bool = False
    verification_reason: str = Field(default="", max_length=1000)
    prompt_id: UUID
    daily_limit: int = Field(default=5, ge=1, le=50)
    threads: int = Field(default=2, ge=1, le=4)
    timeout_seconds: int = Field(default=30, ge=5, le=60)


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


@router.get("/state")
def state() -> dict[str, Any]:
    with connection() as conn:
        result: dict[str, Any] = {
            name: conn.execute(query).fetchall()
            for name, query in {
                "keywords": "SELECT k.*,p.language_code,p.target_country FROM keyword_candidates k JOIN language_profiles p ON p.id=k.profile_id ORDER BY k.collected_at DESC LIMIT 100",
                "sources": "SELECT s.*,r.approved,r.reason AS review_reason,r.reviewer FROM research_sources s LEFT JOIN LATERAL (SELECT * FROM source_reviews WHERE source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true ORDER BY s.collected_at DESC LIMIT 100",
                "profiles": "SELECT p.*,l.display_name,l.active FROM language_profiles p JOIN languages l ON l.code=p.language_code ORDER BY p.language_code,p.target_country",
                "categories": "SELECT * FROM categories ORDER BY slug",
                "settings": "SELECT * FROM generation_settings ORDER BY profile_id",
                "prompts": "SELECT * FROM prompt_templates ORDER BY name,version DESC",
                "jobs": "SELECT r.*,j.keyword_id,j.paused FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id ORDER BY r.created_at DESC LIMIT 100",
                "attempts": "SELECT * FROM generation_attempts ORDER BY id DESC LIMIT 100",
                "versions": "SELECT v.*,g.run_id,g.profile_id,g.provider,g.model,g.prompt_id,g.state,g.result_metadata FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id ORDER BY v.created_at DESC LIMIT 100",
                "schedules": "SELECT * FROM research_schedules ORDER BY next_run_at",
                "dispatches": "SELECT * FROM research_dispatches ORDER BY occurrence DESC LIMIT 100",
            }.items()
        }
        result["controls"] = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        result["events"] = conn.execute(
            "SELECT id,run_id,event_type,payload,created_at FROM audit_events WHERE event_type LIKE 'research.%' ORDER BY id DESC LIMIT 100"
        ).fetchall()
        result["publishing_enabled"] = False
        result["paid_ai_enabled"] = False
        return result


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
                "INSERT INTO source_reviews(source_id,approved,reason,reviewer) VALUES (%s,%s,%s,%s) RETURNING *",
                (source_id, request.approved, request.reason, request.reviewer),
            ).fetchone()
        )


@router.post("/jobs", status_code=201)
def generate(request: Generate) -> dict[str, Any]:
    return pipeline.enqueue(request.keyword_id, request.idempotency_key, request.profile_ids)


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
