"""Durable research-to-internal-draft orchestration. No Blogger dependency."""

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psutil
import psycopg
from croniter import croniter
from psycopg.types.json import Jsonb

from .ai import Draft, EngineFailure, provider
from .article_quality import longest_source_overlap, search_intent_phrase
from .db import connection
from .grounding import inspect, numbers, proper_names
from .localization import EXTRACTOR_VERSION, fact_ledger, localize_fact

EVALUATION_MODEL_ALLOWLIST = {"Qwen3-4B-Q4_K_M.gguf"}


def required(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise EngineFailure("required_database_row_missing")
    return row


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def draft_state(provider_name: str, evaluation_only: bool, checks: dict[str, Any]) -> str:
    if provider_name == "mock":
        return "mock_draft"
    grounding = checks.get("grounding", {})
    if (
        evaluation_only or not checks.get("structural_pass") or not grounding.get("rule_pass")
        or not checks.get("localization_pass", True)
    ):
        return "quality_held"
    return "human_review_required"


def emit(conn: Any, kind: str, run_id: UUID | None = None, **data: Any) -> None:
    conn.execute(
        "INSERT INTO audit_events(run_id,event_type,payload) VALUES (%s,%s,%s)",
        (run_id, "research." + kind, Jsonb(data)),
    )


def run_stage(
    run_id: UUID,
    profile_id: UUID,
    worker_attempt: int,
    sequence: int,
    stage_attempt: int,
    name: str,
    model: str,
    prompt_version: str,
    inputs: dict[str, Any],
    source_ids: list[str],
    operation: Any,
) -> tuple[Any, dict[str, Any], UUID]:
    """Persist and audit one independently executed, inspectable pipeline stage."""
    stage_id = uuid4()
    started = time.monotonic()
    safe_inputs = json.loads(json.dumps(inputs, default=str))
    with connection() as conn:
        lease = conn.execute(
            """UPDATE job_runs r SET lease_until=now()+interval '300 seconds'
            FROM generation_jobs j,pipeline_controls c WHERE r.id=%s AND r.id=j.run_id
            AND r.status='running' AND r.attempts=%s AND r.lease_until>now()
            AND NOT j.paused AND NOT c.paused RETURNING r.id""",
            (run_id, worker_attempt),
        ).fetchone()
        if not lease:
            raise EngineFailure("lease_lost_or_paused")
        conn.execute(
            """INSERT INTO generation_stage_runs
            (id,run_id,profile_id,worker_attempt,stage_attempt,sequence,stage_name,status,
             model,prompt_version,input_snapshot,source_ids)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s,%s)""",
            (
                stage_id, run_id, profile_id, worker_attempt, stage_attempt, sequence, name,
                model, prompt_version, Jsonb(safe_inputs), source_ids,
            ),
        )
        emit(
            conn, "stage.started", run_id, stage_id=str(stage_id), profile_id=str(profile_id),
            name=name, sequence=sequence, stage_attempt=stage_attempt,
            model=model, prompt_version=prompt_version, source_ids=source_ids,
        )
    try:
        output, validation = operation()
        elapsed = int((time.monotonic() - started) * 1000)
        status = "succeeded" if validation.get("passed", True) else "held"
        safe_output = json.loads(json.dumps(output, default=str)) if output is not None else None
        with connection() as conn:
            conn.execute(
                """UPDATE generation_stage_runs SET status=%s,output_snapshot=%s,validation=%s,
                finished_at=now(),elapsed_ms=%s WHERE id=%s AND status='running'""",
                (status, Jsonb(safe_output) if safe_output is not None else None,
                 Jsonb(validation), elapsed, stage_id),
            )
            emit(
                conn, "stage." + status, run_id, stage_id=str(stage_id),
                profile_id=str(profile_id), name=name, sequence=sequence,
                elapsed_ms=elapsed, validation=validation,
            )
        return output, validation, stage_id
    except Exception as exc:
        category = exc.category if isinstance(exc, EngineFailure) else "stage_validation_error"
        elapsed = int((time.monotonic() - started) * 1000)
        status = "cancelled" if category == "generation_cancelled" else "failed"
        with connection() as conn:
            conn.execute(
                """UPDATE generation_stage_runs SET status=%s,error_category=%s,validation=%s,
                finished_at=now(),elapsed_ms=%s WHERE id=%s AND status='running'""",
                (
                    status, category,
                    Jsonb({
                        "passed": False, "error_type": type(exc).__name__,
                        **({"failure_artifact": exc.failure_artifact} if isinstance(exc, EngineFailure) and exc.failure_artifact else {}),
                    }),
                    elapsed, stage_id,
                ),
            )
            emit(
                conn, "stage." + status, run_id, stage_id=str(stage_id),
                profile_id=str(profile_id), name=name, sequence=sequence,
                elapsed_ms=elapsed, error_category=category,
            )
        raise


def evidence_outline(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a bounded outline only from the facts actually present in reviewed sources."""
    if not facts:
        raise EngineFailure("evidence_extraction_empty")
    count = min(4, len(facts))
    groups: list[list[dict[str, str]]] = [[] for _ in range(count)]
    for index, fact in enumerate(facts):
        groups[min(count - 1, index * count // len(facts))].append(fact)
    return [
        {
            "heading": f"Evidence {index + 1}",
            "fact_ids": [fact["fact_id"] for fact in group],
            "source_ids": list(dict.fromkeys(fact["source_id"] for fact in group)),
        }
        for index, group in enumerate(groups)
    ]


def register_fact_registry(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append exact reviewed source spans to the shared immutable fact ledger."""
    registered: list[dict[str, Any]] = []
    with connection() as conn:
        for source in sources:
            source_text = str(source.get("evidence", ""))
            for fact in fact_ledger(source):
                if fact["source_excerpt"] not in source_text:
                    raise EngineFailure("fact_registry_source_span_invalid")
                params = (
                    fact["fact_key"], fact["source_id"], fact["source_language"],
                    fact["source_excerpt"], fact["entity_ids"], Jsonb(fact["numeric_values"]),
                    Jsonb(fact["date_values"]), fact["citation_ids"], EXTRACTOR_VERSION,
                )
                row = conn.execute(
                    """INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,entity_ids,
                        numeric_values,date_values,citation_ids,verification_status,extractor_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'source_span_verified',%s)
                    ON CONFLICT(source_id,fact_key,extractor_version) DO NOTHING RETURNING id""",
                    params,
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT id FROM evidence_facts WHERE source_id=%s AND fact_key=%s AND extractor_version=%s",
                        (fact["source_id"], fact["fact_key"], EXTRACTOR_VERSION),
                    ).fetchone()
                if row is None:
                    raise EngineFailure("fact_registry_persistence_failed")
                registered.append({
                    "fact_id": fact["fact_key"], "registry_id": str(row["id"]),
                    "source_id": fact["source_id"], "text": fact["source_excerpt"],
                    "source_language": fact["source_language"],
                    "entities": fact["entities"],
                    "entity_ids": fact["entity_ids"], "numeric_values": fact["numeric_values"],
                    "date_values": fact["date_values"], "citation_ids": fact["citation_ids"],
                })
    return registered


def section_response_valid(
    draft: Draft, facts: list[dict[str, Any]], allowed_source_ids: set[str], as_of: str
) -> dict[str, Any]:
    material = "\n".join(fact["text"] for fact in facts)
    actual_sources = set(draft.source_ids)
    cited = {match for match in re.findall(r"\[source:([^\]]+)\]", draft.body)}
    names = proper_names(material)
    prose = re.sub(r"\[source:[^\]]+\]", " ", draft.body)
    prose_without_headings = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", prose)
    body_names = proper_names(prose_without_headings)
    unsupported_names = body_names - names
    missing_names = names - body_names
    checks = {
        "source_ids_allowed": bool(actual_sources) and actual_sources.issubset(allowed_source_ids),
        "citations_allowed": cited.issubset(allowed_source_ids) and bool(cited),
        "numbers_from_evidence": numbers(prose_without_headings).issubset(numbers(material + " " + as_of)),
        "proper_names_preserved": not missing_names,
        "no_unsupported_proper_names": not unsupported_names,
        "no_repeated_sentences": len(re.split(r"(?<=[.!?])\s+", prose))
        == len(set(re.split(r"(?<=[.!?])\s+", prose))),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "missing_proper_names": sorted(missing_names),
        "unsupported_proper_names": sorted(unsupported_names),
    }


def render_localized_fact_section(
    facts: list[dict[str, Any]], sources: list[dict[str, Any]], language: str,
    keyword: str, glossary: list[dict[str, Any]], model: str, timeout: int,
    include_title: bool,
) -> tuple[Draft, dict[str, Any]]:
    """Translate fact spans individually, then attach source citations in code."""
    from .grounding import proper_names
    from .local_inference import localized_translation

    copy = {
        "en": ("Verified source facts: ", "This review draft contains only statements tied to the cited official source."),
        "ko": ("공식 자료에서 확인한 사실: ", "이 검토용 초안은 인용한 공식 자료에서 확인한 사실만 담습니다."),
        "zh-CN": ("官方资料核实的要点：", "本审阅草稿仅整理所引官方资料中核实的事实。"),
        "ja": ("公式資料で確認した事実：", "この確認用草稿は引用した公式資料で確認できる事実のみを整理します。"),
    }
    if language not in copy:
        raise EngineFailure("localized_article_copy_not_configured")
    started = time.monotonic()
    source_by_id = {str(source["id"]): source for source in sources}
    localized_rows: list[dict[str, Any]] = []
    model_call_metrics: list[dict[str, Any]] = []
    calls = 0
    for fact in facts:
        source_id = str(fact["source_id"])
        source = source_by_id.get(source_id)
        if source is None or fact["text"] not in str(source.get("evidence", "")):
            raise EngineFailure("fact_registry_source_span_invalid")
        local_fact = {
            **fact,
            "fact_key": fact["fact_id"],
            "source_excerpt": fact["text"],
            "citation_ids": [source_id],
            "source_url": str(source["url"]),
        }
        translation_mode = (
            "faithful_paraphrase" if fact["source_language"] == language else "translate"
        )

        def translate_fact(
            text: str, target: str, approved: list[dict[str, Any]], entities: list[str],
            selected_mode: str = translation_mode,
        ) -> str:
            return localized_translation(
                text, target, approved, entities, model, timeout, selected_mode,
                metrics_sink=model_call_metrics,
            )

        row = localize_fact(
            local_fact,
            language,
            translator=translate_fact,
            glossary=glossary,
            force_local=True,
        )
        calls += int(row["ai_calls"])
        localized_rows.append(row)

    prefix, summary = copy[language]
    concise_keyword = search_intent_phrase(keyword)
    if not concise_keyword:
        raise EngineFailure("search_intent_phrase_requires_review")
    if include_title and language != "en":
        translated_keyword = localized_translation(
            concise_keyword, language, glossary, sorted(proper_names(concise_keyword)), model, timeout,
            metrics_sink=model_call_metrics,
        ).strip()
        calls += 1
    else:
        translated_keyword = concise_keyword
    title = prefix + translated_keyword if include_title else prefix.rstrip()
    body = "\n\n".join(
        str(row["text"]).strip() + " " + " ".join(
            f"[source:{source_id}]" for source_id in row["source_ids"]
        )
        for row in localized_rows
    )
    source_ids = list(dict.fromkeys(
        source_id for row in localized_rows for source_id in row["source_ids"]
    ))
    draft = Draft(
        title=title, body=body, summary=summary,
        keywords=[translated_keyword], source_ids=source_ids,
    )
    checks = {
        row["fact_id"]: {"status": row["status"], **row["checks"]}
        for row in localized_rows
    }
    draft._metrics = {
        "localization_adapter": "per_fact_local_json_translation",
        "localization_facts": len(localized_rows), "model_calls": calls,
        "inference_calls": model_call_metrics,
        "fact_localization_elapsed_ms": sum(int(row["elapsed_ms"]) for row in localized_rows),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "localization_checks": checks,
        "semantic_accuracy": "human_review_required",
        "naturalness": "human_review_required",
    }
    return draft, {
        "passed": all(row["status"] == "machine_passed" for row in localized_rows),
        "fact_checks": checks, "ai_calls": calls,
    }


def evidence(keyword_id: UUID) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT s.*,r.id AS review_id,r.approved,r.reason AS review_reason
            FROM research_sources s JOIN LATERAL
            (SELECT * FROM source_reviews WHERE source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true
            WHERE s.keyword_id=%s AND s.valid_until>now() AND r.approved AND NOT EXISTS(SELECT 1 FROM research_sources newer WHERE newer.keyword_id=s.keyword_id AND newer.url=s.url AND newer.revision>s.revision) ORDER BY s.is_primary DESC,s.id""",
            (keyword_id,),
        ).fetchall()
    if not rows or (not any(r["is_primary"] for r in rows) and len(rows) < 2):
        raise EngineFailure("insufficient_reviewed_evidence")
    return rows


def enqueue(
    keyword_id: UUID, key: str, profile_ids: list[UUID] | None = None, evaluation_only: bool = False,
    evaluation_model: str | None = None,
) -> dict[str, Any]:
    if evaluation_model is not None and (
        not evaluation_only or evaluation_model not in EVALUATION_MODEL_ALLOWLIST
    ):
        raise EngineFailure("evaluation_model_override_blocked")
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781203)")
        keyword = conn.execute(
            "SELECT * FROM keyword_candidates WHERE id=%s", (keyword_id,)
        ).fetchone()
        if (
            not keyword
            or keyword["status"] != "selected"
            or keyword["expires_at"] <= datetime.now(UTC)
        ):
            raise EngineFailure("keyword_not_selected_or_expired")
        targets = conn.execute(
            """SELECT g.*,p.language_code,p.target_country,p.search_intent,p.generation_policy,
            p.localization_policy,p.seo_policy,t.instructions,t.version AS prompt_version
            FROM generation_settings g JOIN language_profiles p ON p.id=g.profile_id
            JOIN languages l ON l.code=p.language_code JOIN prompt_templates t ON t.id=g.prompt_id
            WHERE l.active AND g.enabled ORDER BY (p.id=%s) DESC,p.language_code,p.target_country""",
            (keyword["profile_id"],),
        ).fetchall()
        if profile_ids is not None:
            targets = [t for t in targets if t["profile_id"] in profile_ids]
            if {t["profile_id"] for t in targets} != set(profile_ids):
                raise EngineFailure("inactive_or_unknown_target")
        if not targets:
            raise EngineFailure("source_profile_required")
        if evaluation_only:
            source_profile = conn.execute(
                """SELECT 1 FROM language_profiles p JOIN languages l ON l.code=p.language_code
                WHERE p.id=%s AND l.active""",
                (keyword["profile_id"],),
            ).fetchone()
            if source_profile is None:
                raise EngineFailure("source_profile_required")
        elif targets[0]["profile_id"] != keyword["profile_id"]:
            raise EngineFailure("source_profile_required")
        if evaluation_only and any(t["provider"] != "local" for t in targets):
            raise EngineFailure("evaluation_requires_real_local_provider")
        controls = conn.execute("SELECT evaluation_isolated FROM pipeline_controls").fetchone()
        if evaluation_only and (not controls or not evaluation_database_isolated(conn, controls)):
            raise EngineFailure("evaluation_database_isolation_required")
        if evaluation_only and evaluation_model is not None and any(
            t["engine"] != "llamacpp" for t in targets
        ):
            raise EngineFailure("evaluation_model_override_engine_invalid")
        fingerprint_material: list[Any] = [
            str(keyword_id), sorted(str(t["profile_id"]) for t in targets), evaluation_only,
        ]
        if evaluation_model is not None:
            fingerprint_material.append(evaluation_model)
        fingerprint = hashlib.sha256(json.dumps(fingerprint_material).encode()).hexdigest()
        old = conn.execute(
            "SELECT r.*,g.request_fingerprint FROM job_runs r JOIN generation_jobs g ON g.run_id=r.id WHERE r.idempotency_key=%s",
            (key,),
        ).fetchone()
        if old:
            legacy = hashlib.sha256(
                json.dumps(
                    [str(keyword_id), sorted(str(t["profile_id"]) for t in targets)]
                ).encode()
            ).hexdigest()
            if old["request_fingerprint"] != fingerprint and (
                evaluation_only or old["request_fingerprint"] != legacy
            ):
                raise EngineFailure("idempotency_conflict")
            return old
        if conn.execute("SELECT 1 FROM job_runs WHERE idempotency_key=%s", (key,)).fetchone():
            raise EngineFailure("idempotency_conflict")
        for t in targets:
            quota_column = "evaluation_daily_limit" if evaluation_only else "daily_limit"
            count = conn.execute(
                """SELECT count(*) AS n FROM generation_targets t JOIN generation_jobs j ON j.run_id=t.run_id
                WHERE t.profile_id=%s AND j.evaluation_only=%s AND j.created_at>=(date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')""",
                (t["profile_id"], evaluation_only),
            ).fetchone()
            assert count is not None
            if count["n"] >= t[quota_column]:
                raise EngineFailure(
                    "daily_evaluation_limit" if evaluation_only else "daily_generation_limit"
                )
        run = conn.execute(
            "INSERT INTO job_runs(idempotency_key,task_kind) VALUES (%s,'content') RETURNING *",
            (key,),
        ).fetchone()
        assert run is not None
        conn.execute(
            "INSERT INTO generation_jobs(run_id,keyword_id,request_fingerprint,evaluation_only) VALUES (%s,%s,%s,%s)",
            (run["id"], keyword_id, fingerprint, evaluation_only),
        )
        for t in targets:
            snapshot = json.loads(json.dumps(t, default=str))
            snapshot["evaluation_only"] = evaluation_only
            if evaluation_model is not None:
                snapshot["model"] = evaluation_model
                snapshot["evaluation_model_override"] = True
            conn.execute(
                "INSERT INTO generation_targets VALUES (%s,%s,%s)",
                (run["id"], t["profile_id"], Jsonb(snapshot)),
            )
        if evaluation_model is not None:
            emit(
                conn, "evaluation.model.override", run["id"],
                model=evaluation_model, target_count=len(targets),
                reason="bounded local quality experiment; saved settings unchanged",
            )
        emit(conn, "queued", run["id"], keyword_id=str(keyword_id), targets=len(targets))
        return run


def quality(
    draft: Draft, sources: list[dict[str, Any]], keyword: str, is_mock: bool,
    language: str = "en",
) -> dict[str, Any]:
    text = draft.title + " " + draft.body
    ids = {str(s["id"]) for s in sources}
    search_phrase = search_intent_phrase(keyword) if language == "en" else (draft.keywords[0] if draft.keywords else "")
    checks = {
        "source_ids_valid": bool(draft.source_ids) and set(draft.source_ids).issubset(ids),
        "keyword_in_title_and_body": bool(search_phrase)
        and normalized(search_phrase) in normalized(draft.title)
        and normalized(search_phrase) in normalized(draft.body),
        "structure": "##" in draft.body,
        "as_of_date": datetime.now(UTC).date().isoformat() in draft.body,
        "no_obvious_hype_or_fake_experience": not any(
            term in normalized(text)
            for term in (
                "guaranteed profit",
                "100% return",
                "i visited",
                "?? ??",
                "?? ??",
                "??? ??",
            )
        ),
        "limited_repetition": len([line for line in draft.body.splitlines() if line.strip()])
        == len({line for line in draft.body.splitlines() if line.strip()}),
        "metadata": bool(draft.summary and draft.keywords),
    }
    # Structural checks cannot certify factual truth, translation quality or copyright.
    return {
        "checks": checks,
        "internal_score": round(100 * sum(checks.values()) / len(checks)),
        "structural_pass": all(checks.values()),
        "human_review_required": True,
        "model_quality_verified": False,
        "mock": is_mock,
        "publish_ready": False,
    }


def direct_quote_gate(draft: Draft, sources: list[dict[str, Any]]) -> dict[str, Any]:
    overlap = longest_source_overlap(draft.body, sources)
    return {"no_mass_direct_quote": overlap < 25, "longest_source_overlap_words": overlap}


def _evaluation_source_draft(
    conn: Any, run_id: UUID, keyword_id: UUID, source_profile_id: UUID, evaluation_only: bool
) -> dict[str, Any] | None:
    draft = conn.execute(
        """SELECT v.id,v.title,v.body,g.result_metadata FROM generation_results g
        JOIN content_versions v ON v.id=g.content_version_id
        WHERE g.run_id=%s AND g.profile_id=%s""",
        (run_id, source_profile_id),
    ).fetchone()
    if draft is None and evaluation_only:
        draft = conn.execute(
            """SELECT v.id,v.title,v.body,g.result_metadata
            FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id
            JOIN generation_jobs j ON j.run_id=g.run_id JOIN job_runs r ON r.id=g.run_id
            WHERE j.keyword_id=%s AND j.evaluation_only AND r.status='succeeded'
              AND g.profile_id=%s AND g.content_version_id IS NOT NULL
            ORDER BY r.updated_at DESC,g.created_at DESC LIMIT 1""",
            (keyword_id, source_profile_id),
        ).fetchone()
    return cast(dict[str, Any] | None, draft)


def evaluation_source_prerequisite_met(language: str, source_draft_available: bool) -> bool:
    """Localized evaluation requires a successful source-language draft; English is the source."""
    return language == "en" or source_draft_available


def generate_staged_target(
    run_id: UUID,
    worker_attempt: int,
    profile_id: UUID,
    policy: dict[str, Any],
    keyword: dict[str, Any],
    sources: list[dict[str, Any]],
    glossary: list[dict[str, Any]],
    category: str,
    original_draft: dict[str, Any] | None,
) -> tuple[Draft, dict[str, Any], int]:
    """Execute evidence preparation, outline, per-section generation/localization and gates."""
    model = str(policy["model"])
    prompt_version = str(policy.get("prompt_version", policy["prompt_id"]))
    source_ids = [str(source["id"]) for source in sources]
    sequence = 0

    def execute(
        name: str,
        inputs: dict[str, Any],
        allowed_ids: list[str],
        operation: Any,
        stage_attempt: int = 1,
        sequence_override: int | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        nonlocal sequence
        if sequence_override is None:
            sequence += 1
        else:
            sequence = max(sequence, sequence_override)
        output, validation, _ = run_stage(
            run_id, profile_id, worker_attempt, sequence if sequence_override is None else sequence_override,
            stage_attempt, name,
            model, prompt_version, inputs, allowed_ids, operation,
        )
        return output, validation

    execute(
        "source_collection",
        {"keyword_id": str(keyword["id"]), "reviewed_source_ids": source_ids},
        source_ids,
        lambda: (
            [{"id": str(s["id"]), "url": s["url"], "revision": s["revision"]} for s in sources],
            {"passed": bool(sources), "source_count": len(sources)},
        ),
    )
    facts = register_fact_registry(sources)
    execute(
        "evidence_extraction",
        {"source_ids": source_ids, "method": "verbatim_source_span_fact_ledger"},
        source_ids,
        lambda: (facts, {"passed": bool(facts), "fact_count": len(facts)}),
    )
    execute(
        "fact_registry",
        {"source_ids": source_ids, "method": EXTRACTOR_VERSION,
         "fact_registry_ids": [fact["registry_id"] for fact in facts]},
        source_ids,
        lambda: (facts, {
            "passed": bool(facts) and all(fact["text"] in str(next(
                s["evidence"] for s in sources if str(s["id"]) == fact["source_id"]
            )) for fact in facts),
            "fact_count": len(facts), "source_span_verified": True,
        }),
    )
    source_text = {str(s["id"]): str(s["evidence"]) for s in sources}
    fact_validation = {
        fact["fact_id"]: fact["text"] in source_text.get(fact["source_id"], "")
        for fact in facts
    }
    if not facts or not all(fact_validation.values()):
        raise EngineFailure("evidence_validation_failed")
    execute(
        "evidence_validation",
        {"fact_ids": [fact["fact_id"] for fact in facts]},
        source_ids,
        lambda: (fact_validation, {"passed": all(fact_validation.values()), "method": "exact_source_span"}),
    )
    outline = evidence_outline(facts)
    execute(
        "content_outline",
        {"search_intent": keyword["search_intent"], "fact_ids": [f["fact_id"] for f in facts]},
        source_ids,
        lambda: (outline, {"passed": bool(outline), "method": "evidence_only_bounded_outline"}),
    )

    target_language = str(policy["language_code"])
    is_original = profile_id == keyword["profile_id"]
    source_sections: list[dict[str, Any]] = []
    localized_source = original_draft
    if not is_original:
        if localized_source is None:
            raise EngineFailure("source_version_missing")
        source_metadata = localized_source.get("result_metadata", {})
        source_metrics = source_metadata.get("metrics", {}) if isinstance(source_metadata, dict) else {}
        source_sections = source_metrics.get("section_map", []) if isinstance(source_metrics, dict) else []
        if not source_sections:
            splits = re.split(r"(?m)^##\s+(\d+)\s*$", str(localized_source["body"]))
            for index in range(1, len(splits), 2):
                body = splits[index + 1].strip()
                cited = list(dict.fromkeys(re.findall(r"\[source:([^\]]+)\]", body)))
                section_facts = [f for f in facts if f["source_id"] in cited and f["text"] in body]
                if body and cited and section_facts:
                    source_sections.append(
                        {"heading": splits[index], "body": body, "source_ids": cited,
                         "fact_ids": [f["fact_id"] for f in section_facts]}
                    )
        if not source_sections:
            raise EngineFailure("source_sections_missing")
        outline = [
            {
                "heading": item["heading"],
                "fact_ids": item["fact_ids"],
                "source_ids": item["source_ids"],
                "original_body": item["body"],
            }
            for item in source_sections
        ]

    generated: list[Draft] = []
    generation_started = time.monotonic()
    for index, section in enumerate(outline, start=1):
        section_sequence = sequence + 1
        allowed = set(section["source_ids"])
        section_facts = [f for f in facts if f["fact_id"] in section["fact_ids"]]
        if not section_facts or not allowed.issubset(set(source_ids)):
            raise EngineFailure("outline_evidence_reference_invalid")
        scoped_sources = []
        for source in sources:
            if str(source["id"]) in allowed:
                scoped = dict(source)
                scoped["evidence"] = " ".join(
                    f["text"] for f in section_facts if f["source_id"] == str(source["id"])
                )
                scoped_sources.append(scoped)
        stage_name = "section_generation" if is_original else "localization"
        last_draft: Draft | None = None
        last_errors: list[str] = []
        for stage_attempt in (1, 2):
            instruction = (
                f"Localize only the supplied exact fact spans into {target_language}; "
                "preserve their claim relationships, names, numbers, dates and units. "
                "Do not add background, inference, URLs, quotes, experience or advice."
            )
            if not is_original:
                instruction += " Translate/localize this exact source section; preserve its claim relationships."
            if stage_attempt > 1:
                instruction += (
                    " Previous attempt failed these deterministic checks: "
                    + ", ".join(last_errors)
                    + ". Correct them; do not add facts."
                )
            context = {
                "language_code": target_language,
                "target_country": policy["target_country"],
                "search_intent": policy["search_intent"],
                "generation_policy": policy["generation_policy"],
                "localization_policy": policy["localization_policy"],
                "seo_policy": policy["seo_policy"],
                "instructions": instruction,
                "glossary": glossary,
                "category": category,
                "keyword": keyword["keyword"],
                "as_of": datetime.now(UTC).date().isoformat(),
                "sources": scoped_sources,
                "verified_facts": section_facts,
                "plan": {"section_number": index, "heading": section["heading"]},
            }
            if not is_original:
                assert localized_source is not None
                context["original_draft"] = {
                    "title": str(localized_source["title"]),
                    "body": str(section["original_body"]),
                }

            def operation(
                stage_context: dict[str, Any] = context,
                allowed_facts: list[dict[str, Any]] = section_facts,
                permitted_sources: set[str] = allowed,
                scoped_source_values: list[dict[str, Any]] = scoped_sources,
                section_index: int = index,
            ) -> tuple[dict[str, Any], dict[str, Any]]:
                if policy["provider"] == "mock":
                    result = provider(policy["provider"]).generate(stage_context, policy)
                    return {"draft": result.model_dump(), "metrics": result._metrics}, {
                        "passed": bool(result.source_ids)
                        and set(result.source_ids).issubset(permitted_sources),
                        "synthetic_mock": True,
                    }
                rendered, localization_validation = render_localized_fact_section(
                    allowed_facts, scoped_source_values, target_language,
                    str(stage_context["keyword"]), glossary, model,
                    int(policy.get("timeout_seconds", 120)), section_index == 1,
                )
                validation = section_response_valid(
                    rendered, allowed_facts, permitted_sources, stage_context["as_of"]
                )
                validation["localization"] = localization_validation
                validation["passed"] = bool(validation["passed"] and localization_validation["passed"])
                return {"draft": rendered.model_dump(), "metrics": rendered._metrics}, validation

            try:
                value, validation = execute(
                    stage_name,
                    {"section": index, "fact_ids": [f["fact_id"] for f in section_facts],
                     "target_language": target_language, "source_section": context.get("original_draft")},
                    sorted(allowed),
                    operation,
                    stage_attempt,
                    section_sequence,
                )
                last_draft = Draft.model_validate(value["draft"])
                last_draft._metrics = value.get("metrics", {})
                if validation.get("passed"):
                    break
                result_checks = validation.get("checks", {})
                last_errors = [name for name, passed in result_checks.items() if not passed]
                localization_report = validation.get("localization")
                if localization_report and not localization_report.get("passed"):
                    last_errors = ["localized_fact_quality_held"]
                    break
            except EngineFailure as exc:
                retryable_validation = exc.category in {
                    "invalid_local_model_response", "local_model_timeout", "model_response_too_large",
                    "fact_render_contract_size_invalid", "fact_render_contract_marker_invalid",
                    "fact_render_contract_marker_duplicate", "fact_render_contract_coverage_invalid",
                }
                if stage_attempt == 2 or (not exc.retryable and not retryable_validation):
                    raise
                last_errors = [exc.category]
        if last_draft is None:
            raise EngineFailure("stage_generation_failed")
        generated.append(last_draft)

    first = generated[0]
    draft = Draft(
        title=first.title,
        body=f"## {first.keywords[0]}\n\n" + "\n\n".join(
            f"## {index}\n{section.body.strip()}" for index, section in enumerate(generated, start=1)
        ) + f"\n\n{datetime.now(UTC).date().isoformat()}",
        summary=first.summary,
        keywords=first.keywords,
        source_ids=list(dict.fromkeys(source_id for section in generated for source_id in section.source_ids)),
    )
    section_map = [
        {
            "heading": str(index),
            "body": section.body.strip(),
            "source_ids": section.source_ids,
            "fact_ids": outline[index - 1]["fact_ids"],
        }
        for index, section in enumerate(generated, start=1)
    ]
    stage_metrics = {"section_count": len(generated), "model_time_ms": int((time.monotonic() - generation_started) * 1000)}
    return draft, {
        "outline": outline,
        "fact_registry": facts,
        "section_map": section_map,
        "section_metrics": [s._metrics for s in generated],
        "stage_metrics": stage_metrics,
    }, sequence


def process(run: dict[str, Any]) -> None:
    run_id, attempt = run["id"], run["attempts"]
    with connection() as conn:
        job = conn.execute("SELECT * FROM generation_jobs WHERE run_id=%s", (run_id,)).fetchone()
        assert job is not None
        keyword = conn.execute(
            "SELECT * FROM keyword_candidates WHERE id=%s", (job["keyword_id"],)
        ).fetchone()
        assert keyword is not None
        targets = conn.execute(
            "SELECT * FROM generation_targets WHERE run_id=%s ORDER BY (profile_id=%s) DESC,profile_id",
            (run_id, keyword["profile_id"]),
        ).fetchall()
    if keyword["status"] != "selected" or keyword["expires_at"] <= datetime.now(UTC):
        raise EngineFailure("keyword_not_selected_or_expired")
    try:
        sources = evidence(keyword["id"])
    except EngineFailure as exc:
        failure_category = exc.category
        failure_retryable = exc.retryable
        for target in targets:
            snapshot = target["settings_snapshot"]

            def blocked_collection(
                category: str = failure_category, retryable: bool = failure_retryable
            ) -> tuple[None, dict[str, Any]]:
                raise EngineFailure(category, retryable)

            try:
                run_stage(
                    run_id, target["profile_id"], attempt, 1, 1, "source_collection",
                    str(snapshot["model"]), str(snapshot.get("prompt_version", snapshot["prompt_id"])),
                    {"keyword_id": str(keyword["id"]), "blocked": True}, [], blocked_collection,
                )
            except EngineFailure:
                pass
        raise
    for target in targets:
        profile_id = target["profile_id"]
        with connection() as conn:
            if conn.execute(
                "SELECT 1 FROM generation_results WHERE run_id=%s AND profile_id=%s",
                (run_id, profile_id),
            ).fetchone():
                continue
            active = conn.execute(
                "SELECT l.active,g.enabled,g.language_verified,g.provider,g.model FROM language_profiles p JOIN languages l ON l.code=p.language_code JOIN generation_settings g ON g.profile_id=p.id WHERE p.id=%s",
                (profile_id,),
            ).fetchone()
            if not active or not active["active"]:
                raise EngineFailure("language_disabled")
            if not active["enabled"]:
                raise EngineFailure("profile_processing_disabled")
            snapshot = target["settings_snapshot"]
            if snapshot["provider"] == "local" and (
                (not active["language_verified"] and not snapshot.get("evaluation_only"))
                or active["provider"] != "local"
                or (
                    active["model"] != snapshot["model"]
                    and not (
                        snapshot.get("evaluation_only")
                        and snapshot.get("evaluation_model_override")
                        and snapshot["model"] in EVALUATION_MODEL_ALLOWLIST
                    )
                )
            ):
                raise EngineFailure("language_support_unverified")
            lease = conn.execute(
                """UPDATE job_runs r SET lease_until=now()+interval '300 seconds'
                FROM generation_jobs j,pipeline_controls c WHERE r.id=%s AND r.id=j.run_id AND r.status='running'
                AND r.attempts=%s AND NOT j.paused AND NOT c.paused AND r.lease_until>now() RETURNING r.id""",
                (run_id, attempt),
            ).fetchone()
            if not lease:
                raise EngineFailure("lease_lost_or_paused")
            emit(conn, "generation.started", run_id, profile_id=str(profile_id), attempt=attempt)
        policy = target["settings_snapshot"]
        with connection() as conn:
            emit(
                conn,
                "facts.checked",
                run_id,
                profile_id=str(profile_id),
                source_count=len(sources),
                verification="recorded_source_attestation",
            )
        with connection() as conn:
            glossary = conn.execute(
                """SELECT source_term,localized_term,notes,source_language,target_language,
                    official_translation,translation_source,approved
                FROM glossary_entries WHERE profile_id=%s""",
                (profile_id,),
            ).fetchall()
            category = required(
                conn.execute(
                    "SELECT slug FROM categories WHERE id=%s", (keyword["category_id"],)
                ).fetchone()
            )
        with connection() as conn:
            source_draft = _evaluation_source_draft(
                conn, run_id, keyword["id"], keyword["profile_id"],
                bool(policy.get("evaluation_only")),
            )
        started = time.monotonic()
        draft, stage_details, stage_sequence = generate_staged_target(
            run_id,
            attempt,
            profile_id,
            policy,
            keyword,
            sources,
            glossary,
            category["slug"],
            json.loads(json.dumps(source_draft, default=str)) if source_draft else None,
        )
        draft._metrics = stage_details
        context = {
            "language_code": policy["language_code"],
            "target_country": policy["target_country"],
            "keyword": keyword["keyword"],
            "as_of": datetime.now(UTC).date().isoformat(),
            "sources": json.loads(json.dumps(sources, default=str)),
            "verified_facts": stage_details["fact_registry"],
            "outline": stage_details["outline"],
            "stage_count": stage_sequence,
            "original_profile_id": str(keyword["profile_id"]),
        }
        with connection() as conn:
            emit(conn, "planning.completed", run_id, profile_id=str(profile_id), plan={"outline": stage_details["outline"]})
        checks = quality(
            draft, sources, keyword["keyword"], policy["provider"] == "mock", policy["language_code"]
        )
        if policy["provider"] == "local":
            checks["grounding"] = inspect(draft, sources, policy["language_code"], context["as_of"])
            quote_check = direct_quote_gate(draft, sources)
            grounding_checks = checks["grounding"]["rule_checks"]
            grounding_checks["no_mass_direct_quote"] = quote_check["no_mass_direct_quote"]
            checks["grounding"]["rule_pass"] = all(grounding_checks.values())
            checks["grounding"].update(quote_check)
            localization_checks = {
                fact_id: fact_result
                for section_metrics in stage_details["section_metrics"]
                for fact_id, fact_result in section_metrics.get("localization_checks", {}).items()
            }
            checks["localization"] = localization_checks
            checks["localization_pass"] = all(
                result.get("status") == "machine_passed" for result in localization_checks.values()
            )
        execute_index = stage_sequence + 1
        run_stage(
            run_id, profile_id, attempt, execute_index, 1, "claim_verification",
            str(policy["model"]), str(policy.get("prompt_version", policy["prompt_id"])),
            {"content_hash": hashlib.sha256(normalized(draft.body).encode()).hexdigest(),
             "source_ids": draft.source_ids}, draft.source_ids,
            lambda current_checks=checks: (
                current_checks.get("grounding", current_checks),
                {"passed": bool(
                    current_checks.get("grounding", {}).get("rule_pass", current_checks["structural_pass"])
                    and current_checks.get("localization_pass", True)
                )},
            ),
        )
        run_stage(
            run_id, profile_id, attempt, execute_index + 1, 1, "seo_quality",
            str(policy["model"]), str(policy.get("prompt_version", policy["prompt_id"])),
            {"language": policy["language_code"], "title": draft.title, "keywords": draft.keywords},
            draft.source_ids,
            lambda current_checks=checks: (
                current_checks,
                {"passed": bool(
                    current_checks["structural_pass"]
                    and current_checks.get("grounding", {}).get("rule_pass", True)
                    and current_checks.get("localization_pass", True)
                )},
            ),
        )
        if not checks["structural_pass"] and policy["provider"] == "mock":
            raise EngineFailure("quality_checks_failed")
        digest = hashlib.sha256(normalized(draft.body).encode()).hexdigest()
        with connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(781204)")
            current = conn.execute(
                """SELECT r.id FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
                CROSS JOIN pipeline_controls c WHERE r.id=%s AND r.status='running' AND r.attempts=%s
                AND r.lease_until>now() AND NOT j.paused AND NOT c.paused FOR UPDATE OF r,j""",
                (run_id, attempt),
            ).fetchone()
            if not current:
                raise EngineFailure("lease_lost_or_paused")
            # Recheck revoked/expired evidence immediately before persistence.
            if {str(s["review_id"]) for s in evidence(keyword["id"])} != {
                str(s["review_id"]) for s in sources
            }:
                raise EngineFailure("evidence_changed")
            previous = conn.execute(
                """SELECT v.body FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id
                WHERE g.profile_id=%s""",
                (profile_id,),
            ).fetchall()
            if any(
                SequenceMatcher(None, normalized(p["body"]), normalized(draft.body)).ratio() >= 0.97
                for p in previous
            ):
                raise EngineFailure("duplicate_content")
            k = conn.execute(
                "SELECT group_id FROM keyword_candidates WHERE id=%s FOR UPDATE", (keyword["id"],)
            ).fetchone()
            assert k is not None
            group_id = k["group_id"]
            if not group_id:
                group_id = required(
                    conn.execute(
                        "INSERT INTO content_groups DEFAULT VALUES RETURNING id"
                    ).fetchone()
                )["id"]
                conn.execute(
                    "UPDATE keyword_candidates SET group_id=%s WHERE id=%s",
                    (group_id, keyword["id"]),
                )
            localization_row = conn.execute(
                """INSERT INTO content_localizations(group_id,language_code,target_country) VALUES (%s,%s,%s)
                ON CONFLICT(group_id,language_code,target_country) DO NOTHING RETURNING id""",
                (group_id, policy["language_code"], policy["target_country"]),
            ).fetchone()
            localization = required(
                localization_row
                or conn.execute(
                    "SELECT id FROM content_localizations WHERE group_id=%s AND language_code=%s AND target_country=%s",
                    (group_id, policy["language_code"], policy["target_country"]),
                ).fetchone()
            )["id"]
            source_version = None
            if profile_id != keyword["profile_id"]:
                source = conn.execute(
                    "SELECT content_version_id FROM generation_results WHERE run_id=%s AND profile_id=%s",
                    (run_id, keyword["profile_id"]),
                ).fetchone()
                if not source and policy.get("evaluation_only") and source_draft is not None:
                    source = {"content_version_id": source_draft["id"]}
                if not source and not policy.get("evaluation_only"):
                    raise EngineFailure("source_version_missing")
                if source:
                    source_version = source["content_version_id"]
            number = required(
                conn.execute(
                    "SELECT coalesce(max(version),0)+1 AS n FROM content_versions WHERE localization_id=%s",
                    (localization,),
                ).fetchone()
            )["n"]
            version = required(
                conn.execute(
                    """INSERT INTO content_versions(group_id,language,localization_id,version,title,body,source_version_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (
                        group_id,
                        policy["language_code"],
                        localization,
                        number,
                        draft.title,
                        draft.body,
                        source_version,
                    ),
                ).fetchone()
            )["id"]
            conn.execute(
                "INSERT INTO localization_categories VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (localization, keyword["category_id"]),
            )
            conn.execute(
                """INSERT INTO generation_results(run_id,profile_id,content_version_id,provider,model,prompt_id,prompt_snapshot,
                source_snapshot,result_metadata,content_hash,elapsed_ms,state) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    run_id,
                    profile_id,
                    version,
                    policy["provider"],
                    policy["model"],
                    policy["prompt_id"],
                    Jsonb({"settings": policy, "context": context}),
                    Jsonb(context["sources"]),
                    Jsonb(
                        {
                            "summary": draft.summary,
                            "keywords": draft.keywords,
                            "referenced_source_ids": draft.source_ids,
                            "quality": checks,
                            "metrics": draft._metrics,
                        }
                    ),
                    digest,
                    int((time.monotonic() - started) * 1000),
                    draft_state(policy["provider"], policy.get("evaluation_only", False), checks),
                ),
            )
            conn.execute(
                "INSERT INTO seo_audits(content_version_id,profile_id,passed,validator_adapter,checks) VALUES (%s,%s,false,'internal-structural-v1',%s)",
                (version, profile_id, Jsonb(checks)),
            )
            emit(
                conn,
                "generation.saved",
                run_id,
                profile_id=str(profile_id),
                version_id=str(version),
                version=number,
                state="internal_draft",
            )
            emit(conn, "seo.checked", run_id, profile_id=str(profile_id), publish_ready=False)
        run_stage(
            run_id,
            profile_id,
            attempt,
            execute_index + 2,
            1,
            "draft_persistence",
            str(policy["model"]),
            str(policy.get("prompt_version", policy["prompt_id"])),
            {"content_hash": digest, "version": number},
            draft.source_ids,
            lambda version_id=version, version_number=number: (
                {"content_version_id": str(version_id), "version": version_number}, {"passed": True}
            ),
        )


def resources_ok(controls: dict[str, Any]) -> bool:
    ram = psutil.virtual_memory()
    project_root = Path(__file__).resolve().parents[3]
    disk = psutil.disk_usage(str(project_root))
    return bool(
        psutil.cpu_percent(interval=0.1) < controls["cpu_percent"]
        and ram.percent < controls["ram_percent"]
        and ram.available >= 6 * 1024**3
        and disk.free >= 10 * 1024**3
    )


def daily_batch_capacity_available(target_count: int, daily_limit: int, new_jobs: int) -> bool:
    """Require capacity for the whole bounded batch before enqueueing any of it."""
    return (
        target_count >= 0 and daily_limit >= 0 and new_jobs >= 0
        and target_count + new_jobs <= daily_limit
    )


def evaluation_database_isolated(conn: Any, controls: dict[str, Any]) -> bool:
    operations_url = os.environ.get("WOORI_OPERATION_DATABASE_URL", "")
    if not controls.get("evaluation_isolated") or not operations_url:
        return False
    current = conn.execute("SELECT current_database() AS name").fetchone()
    if current is None:
        return False
    try:
        with psycopg.connect(operations_url, connect_timeout=2) as operations:
            row = operations.execute("SELECT current_database()").fetchone()
    except psycopg.Error:
        return False
    return bool(row and current["name"] != row[0])


def tick(evaluation_only: bool = False) -> bool:
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781205)")
        recovered = conn.execute("""UPDATE job_runs r SET status=CASE WHEN r.attempts>=3 THEN 'failed' ELSE 'queued' END,
            lease_until=NULL,error_type='LeaseExpired',error_message='Content lease expired',error_location='pipeline',error_at=now(),updated_at=now()
            FROM generation_jobs j WHERE j.run_id=r.id AND r.task_kind='content' AND j.evaluation_only=%s
            AND r.status='running' AND r.lease_until<now() RETURNING r.id,r.status,r.attempts""", (evaluation_only,)).fetchall()
        for r in recovered:
            emit(conn, "recovered", r["id"], status=r["status"], attempt=r["attempts"])
            interrupted = conn.execute(
                """UPDATE generation_stage_runs SET status='failed',error_category='worker_interrupted',
                validation='{"passed":false,"recovery":"lease_expired"}'::jsonb,
                finished_at=now(),elapsed_ms=(extract(epoch FROM now()-started_at)*1000)::integer
                WHERE run_id=%s AND status='running' RETURNING id,profile_id,stage_name,sequence""",
                (r["id"],),
            ).fetchall()
            for stage in interrupted:
                emit(
                    conn, "stage.recovered", r["id"], stage_id=str(stage["id"]),
                    profile_id=str(stage["profile_id"]), name=stage["stage_name"],
                    sequence=stage["sequence"], error_category="worker_interrupted",
                )
            conn.execute(
                "INSERT INTO generation_attempts(run_id,attempt,event,error_category) VALUES (%s,%s,'recovered','lease_expired')",
                (r["id"], r["attempts"]),
            )
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        assert controls is not None
        if evaluation_only and not evaluation_database_isolated(conn, controls):
            return False
        if controls["paused"] or not resources_ok(controls):
            return False
        running = required(
            conn.execute(
                "SELECT count(*) AS n FROM job_runs WHERE task_kind='content' AND status='running'"
            ).fetchone()
        )["n"]
        if running >= controls["max_concurrency"]:
            return False
        run = conn.execute("""SELECT r.* FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
            WHERE r.task_kind='content' AND j.evaluation_only=%s AND r.status='queued' AND NOT j.paused AND r.available_at<=now()
            ORDER BY r.created_at FOR UPDATE OF r SKIP LOCKED LIMIT 1""", (evaluation_only,)).fetchone()
        if not run:
            return False
        run = conn.execute(
            """UPDATE job_runs SET status='running',attempts=attempts+1,lease_until=now()+interval '300 seconds',
            updated_at=now() WHERE id=%s RETURNING *""",
            (run["id"],),
        ).fetchone()
        assert run is not None
        memory = psutil.virtual_memory()
        process_memory = psutil.Process().memory_info().rss
        emit(
            conn, "started", run["id"], attempt=run["attempts"],
            evaluation_only=evaluation_only,
            cpu_percent=psutil.cpu_percent(interval=None),
            ram_used_percent=memory.percent,
            ram_available_bytes=memory.available,
            worker_rss_bytes=process_memory,
        )
    try:
        process(run)
    except Exception as exc:  # noqa: BLE001 - terminalize the durable job on unexpected failure
        category = exc.category if isinstance(exc, EngineFailure) else "internal_generation_error"
        retry = (
            isinstance(exc, EngineFailure) and exc.retryable and run["attempts"] < 3
        ) or category in ("lease_lost_or_paused", "generation_cancelled")
        with connection() as conn:
            changed = conn.execute(
                """UPDATE job_runs SET status=%s,lease_until=NULL,available_at=now()+interval '30 seconds',
                error_type=%s,error_message=%s,error_location='pipeline',error_at=now(),updated_at=now()
                WHERE id=%s AND status='running' AND attempts=%s RETURNING id""",
                ("queued" if retry else "failed", category, category, run["id"], run["attempts"]),
            ).fetchone()
            if changed:
                emit(
                    conn,
                    "retry" if retry else "failed",
                    run["id"],
                    category=category,
                    attempt=run["attempts"],
                )
                conn.execute(
                    "INSERT INTO generation_attempts(run_id,attempt,event,error_category) VALUES (%s,%s,%s,%s)",
                    (run["id"], run["attempts"], "retry" if retry else "failed", category),
                )
    else:
        with connection() as conn:
            changed = conn.execute(
                """UPDATE job_runs SET status='succeeded',lease_until=NULL,resolution='Internal drafts saved; publication blocked',updated_at=now()
                WHERE id=%s AND status='running' AND attempts=%s RETURNING id""",
                (run["id"], run["attempts"]),
            ).fetchone()
            if changed:
                emit(conn, "completed", run["id"], attempt=run["attempts"])
    return True


def schedule_tick() -> None:
    from zoneinfo import ZoneInfo

    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(781203)")
        if required(conn.execute("SELECT paused FROM pipeline_controls").fetchone())["paused"]:
            return
        schedules = conn.execute(
            "SELECT * FROM research_schedules WHERE active AND next_run_at<=now() FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for s in schedules:
            candidates = conn.execute(
                """SELECT k.id FROM keyword_candidates k JOIN generation_settings g ON g.profile_id=k.profile_id
                JOIN language_profiles p ON p.id=k.profile_id JOIN languages l ON l.code=p.language_code
                WHERE k.category_id=%s AND k.profile_id=%s AND k.status='selected' AND k.expires_at>now() AND l.active AND g.enabled
                AND NOT EXISTS(SELECT 1 FROM generation_jobs j WHERE j.keyword_id=k.id)
                ORDER BY k.priority DESC,k.collected_at LIMIT %s""",
                (s["category_id"], s["profile_id"], s["quantity"]),
            ).fetchall()
            # Enqueue inside this transaction via shared helper connection is not safe: gather after commit.
            next_at = croniter(s["schedule_cron"], datetime.now(ZoneInfo(s["timezone"]))).get_next(
                datetime
            )
            conn.execute(
                "UPDATE research_schedules SET next_run_at=%s WHERE id=%s", (next_at, s["id"])
            )
            emit(conn, "schedule.due", schedule_id=str(s["id"]), candidates=len(candidates))
            for k in candidates:
                # Durable occurrence key; dispatch is reconciled by the scheduler outbox below.
                conn.execute(
                    "INSERT INTO research_dispatches(schedule_id,keyword_id,occurrence) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (s["id"], k["id"], s["next_run_at"]),
                )
    with connection() as conn:
        pending = conn.execute(
            "SELECT * FROM research_dispatches WHERE dispatched_at IS NULL ORDER BY occurrence LIMIT 10"
        ).fetchall()
    for d in pending:
        try:
            enqueue(d["keyword_id"], "schedule-" + str(d["id"]))
        except EngineFailure as exc:
            with connection() as conn:
                conn.execute(
                    "UPDATE research_dispatches SET error_category=%s WHERE id=%s",
                    (exc.category, d["id"]),
                )
            continue
        with connection() as conn:
            conn.execute(
                "UPDATE research_dispatches SET dispatched_at=now(),error_category=NULL WHERE id=%s",
                (d["id"],),
            )
