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
        result["publishing_enabled"] = False
        result["paid_ai_enabled"] = False
        return result


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
