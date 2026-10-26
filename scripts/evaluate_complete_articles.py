"""Collect two official sources and save evidence-led four-language draft evaluations."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psutil
from psycopg.types.json import Jsonb
from woori import collection
from woori.ai import EngineFailure
from woori.article_quality import evaluate
from woori.db import connection
from woori.local_inference import LlamaCppProvider, runtime
from woori.localization import EXTRACTOR_VERSION, fact_ledger

ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = "p3.8-c1-full-article-v1"
EXPECTED_MODEL = "Qwen3-4B-Q4_K_M.gguf"


def audit(event: str, **payload: object) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (event, Jsonb(payload)),
        )


def collect_sources(batch_id: UUID) -> list[dict[str, object]]:
    if not os.getenv("SEC_USER_AGENT_CONTACT", "").strip():
        raise SystemExit("SEC_USER_AGENT_CONTACT is required for identified EDGAR access")
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,adapter,profile_id FROM collection_sources WHERE adapter IN ('fed_rss','sec_edgar') AND active ORDER BY adapter"
        ).fetchall()
        fallback_profile = conn.execute(
            """SELECT p.id FROM language_profiles p JOIN languages l ON l.code=p.language_code
            WHERE l.active AND p.target_country='' ORDER BY CASE WHEN p.language_code='en' THEN 0 ELSE 1 END,
            p.language_code LIMIT 1"""
        ).fetchone()
    if {row["adapter"] for row in rows} != {"fed_rss", "sec_edgar"}:
        raise SystemExit("Both reviewed Federal Reserve and SEC collection sources must be active")
    jobs: list[tuple[str, UUID]] = []
    for row in rows:
        profile_id = row["profile_id"] or (fallback_profile["id"] if fallback_profile else None)
        if profile_id is None:
            raise SystemExit(f"No active source profile for {row['adapter']}")
        job = collection.request(
            row["id"], profile_id, f"p38c1-{batch_id.hex}-{row['adapter']}", False
        )
        jobs.append((row["adapter"], job["id"]))
    for adapter, job_id in jobs:
        for _ in range(4):
            collection.tick(run_id=job_id)
            with connection() as conn:
                current = conn.execute(
                    "SELECT status,error_type,available_at FROM job_runs WHERE id=%s", (job_id,)
                ).fetchone()
            if current["status"] == "succeeded":
                break
            if current["status"] == "failed":
                raise SystemExit(f"{adapter} collection failed: {current['error_type']}")
            seconds = max(0, (current["available_at"] - datetime.now(UTC)).total_seconds())
            if seconds:
                time.sleep(min(seconds, 60))
        else:
            raise SystemExit(f"{adapter} collection did not complete within bounded retries")
    output: list[dict[str, object]] = []
    with connection() as conn:
        for adapter, _job in jobs:
            row = conn.execute(
                """SELECT s.*,COALESCE(NULLIF(r.source_language,'und'),s.source_language) AS reviewed_source_language,
                    r.approved,r.reason AS review_reason,i.collected_at AS retrieved_at,k.keyword,k.category_id,c.slug AS category
                FROM collection_sources cs JOIN collection_items i ON i.source_id=cs.id
                JOIN research_sources s ON s.id=i.research_source_id
                JOIN keyword_candidates k ON k.id=i.keyword_id JOIN categories c ON c.id=k.category_id
                JOIN LATERAL (SELECT * FROM source_reviews WHERE source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true
                WHERE cs.adapter=%s AND r.approved AND s.valid_until>now()
                ORDER BY i.collected_at DESC LIMIT 1""",
                (adapter,),
            ).fetchone()
            if not row:
                raise SystemExit(f"{adapter} has no current reviewed source")
            row["source_language"] = row.pop("reviewed_source_language")
            if row["source_language"] != "en":
                raise SystemExit(
                    f"{adapter} source language attribution is not reviewed as English"
                )
            output.append(dict(row))
    return output


def reviewed_sources() -> list[dict[str, object]]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT s.*,COALESCE(NULLIF(r.source_language,'und'),s.source_language) AS reviewed_source_language,
                r.approved,r.reason AS review_reason,i.collected_at AS retrieved_at,k.keyword,k.category_id,c.slug AS category
            FROM collection_sources cs JOIN collection_items i ON i.source_id=cs.id
            JOIN research_sources s ON s.id=i.research_source_id JOIN keyword_candidates k ON k.id=i.keyword_id
            JOIN categories c ON c.id=k.category_id
            JOIN LATERAL (SELECT * FROM source_reviews WHERE source_id=s.id ORDER BY review_sequence DESC LIMIT 1) r ON true
            WHERE cs.adapter IN ('fed_rss','sec_edgar') AND r.approved AND s.valid_until>now()
            AND NOT EXISTS (SELECT 1 FROM research_sources newer WHERE newer.keyword_id=s.keyword_id AND newer.url=s.url AND newer.revision>s.revision)
            ORDER BY cs.adapter,i.collected_at DESC"""
        ).fetchall()
    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        adapter = "sec_edgar" if row["source_name"].startswith("SEC EDGAR") else "fed_rss"
        selected.setdefault(adapter, dict(row))
    if set(selected) != {"fed_rss", "sec_edgar"}:
        raise SystemExit("Need one current reviewed Federal Reserve and SEC source")
    for row in selected.values():
        row["source_language"] = row.pop("reviewed_source_language")
    return [selected["fed_rss"], selected["sec_edgar"]]


def store_facts(source: dict[str, object]) -> list[dict[str, object]]:
    facts = fact_ledger(source)
    if len(facts) < 2:
        raise SystemExit(f"Source has insufficient independent evidence spans: {source['id']}")
    stored = []
    with connection() as conn:
        for fact in facts:
            row = conn.execute(
                """INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,entity_ids,
                    numeric_values,date_values,citation_ids,verification_status,extractor_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'source_span_verified',%s)
                ON CONFLICT(source_id,fact_key,extractor_version) DO NOTHING RETURNING id""",
                (
                    fact["fact_key"],
                    fact["source_id"],
                    fact["source_language"],
                    fact["source_excerpt"],
                    fact["entity_ids"],
                    Jsonb(fact["numeric_values"]),
                    Jsonb(fact["date_values"]),
                    [UUID(x) for x in fact["citation_ids"]],
                    EXTRACTOR_VERSION,
                ),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT id FROM evidence_facts WHERE source_id=%s AND fact_key=%s AND extractor_version=%s",
                    (fact["source_id"], fact["fact_key"], EXTRACTOR_VERSION),
                ).fetchone()
            stored.append({**fact, "id": row["id"]})
    return stored


def save_article(
    batch_id: UUID,
    topic_key: str,
    source: dict[str, object],
    facts: list[dict[str, object]],
    language: str,
    result: dict[str, object],
) -> dict[str, object]:
    draft = result.get("draft")
    quality = result["quality"]
    with connection() as conn:
        if draft is None:
            conn.execute(
                """INSERT INTO article_quality_evaluations(batch_id,topic_key,topic,language_code,title,source_ids,fact_ids,
                    model,prompt_version,metrics,checks,machine_passed,status,error_category,elapsed_ms,ai_calls)
                VALUES (%s,%s,%s,%s,'',%s,%s,%s,%s,%s,%s,false,'failed',%s,%s,1)""",
                (
                    batch_id,
                    topic_key,
                    str(source["keyword"]),
                    language,
                    [source["id"]],
                    [fact["id"] for fact in facts],
                    EXPECTED_MODEL,
                    PROMPT_VERSION,
                    Jsonb(result["metrics"]),
                    Jsonb({}),
                    result.get("error_category"),
                    result["elapsed_ms"],
                ),
            )
            evaluation_id = conn.execute(
                "SELECT id FROM article_quality_evaluations WHERE batch_id=%s AND topic_key=%s AND language_code=%s",
                (batch_id, topic_key, language),
            ).fetchone()["id"]
            return {
                "id": str(evaluation_id),
                "topic_key": topic_key,
                "language": language,
                "status": "failed",
                "error_category": result.get("error_category"),
                "elapsed_ms": result["elapsed_ms"],
                "ai_calls": 1,
                "publish_ready": False,
            }

        group_id = result["group_id"]
        parent_id = result.get("parent_version_id")
        version_number = conn.execute(
            "SELECT coalesce(max(version),0)+1 AS v FROM content_versions WHERE group_id=%s AND language=%s",
            (group_id, language),
        ).fetchone()["v"]
        version = conn.execute(
            """INSERT INTO content_versions(group_id,language,version,title,body,source_version_id)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (group_id, language, version_number, draft.title, draft.body, parent_id),
        ).fetchone()
        profile = conn.execute(
            "SELECT id FROM language_profiles WHERE language_code=%s AND target_country=''",
            (language,),
        ).fetchone()
        conn.execute(
            """INSERT INTO seo_audits(content_version_id,profile_id,passed,validator_adapter,checks)
            VALUES (%s,%s,%s,%s,%s)""",
            (
                version["id"],
                profile["id"],
                bool(quality["machine_passed"]),
                "article_quality_v1",
                Jsonb(quality),
            ),
        )
        conn.execute(
            """INSERT INTO article_quality_evaluations(batch_id,topic_key,topic,language_code,content_version_id,title,
                source_ids,fact_ids,summary,keywords,model,prompt_version,metrics,checks,machine_passed,status,elapsed_ms,ai_calls)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
            (
                batch_id,
                topic_key,
                str(source["keyword"]),
                language,
                version["id"],
                draft.title,
                [source["id"]],
                [fact["id"] for fact in facts],
                draft.summary,
                draft.keywords,
                EXPECTED_MODEL,
                PROMPT_VERSION,
                Jsonb(result["metrics"]),
                Jsonb(quality["checks"]),
                bool(quality["machine_passed"]),
                "machine_passed_review_required" if quality["machine_passed"] else "quality_held",
                result["elapsed_ms"],
            ),
        )
        conn.execute(
            "INSERT INTO localization_categories(localization_id,category_id) SELECT localization_id,%s FROM content_versions WHERE id=%s ON CONFLICT DO NOTHING",
            (source["category_id"], version["id"]),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('article.draft.evaluated',%s)",
            (
                Jsonb(
                    {
                        "batch_id": str(batch_id),
                        "topic_key": topic_key,
                        "content_version_id": str(version["id"]),
                        "language": language,
                        "status": "machine_passed_review_required"
                        if quality["machine_passed"]
                        else "quality_held",
                        "publish_ready": False,
                    }
                ),
            ),
        )
        evaluation_id = conn.execute(
            "SELECT id FROM article_quality_evaluations WHERE batch_id=%s AND topic_key=%s AND language_code=%s",
            (batch_id, topic_key, language),
        ).fetchone()["id"]
    return {
        "id": str(evaluation_id),
        "version_id": str(version["id"]),
        "group_id": str(group_id),
        "topic_key": topic_key,
        "language": language,
        "title": draft.title,
        "summary": draft.summary,
        "keywords": draft.keywords,
        "body": draft.body,
        "status": (
            "machine_passed_review_required" if quality["machine_passed"] else "quality_held"
        ),
        "quality": quality,
        "metrics": result["metrics"],
        "elapsed_ms": result["elapsed_ms"],
        "ai_calls": 1,
        "publish_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-collection", action="store_true", help="Use latest current reviewed saved sources"
    )
    parser.add_argument("--batch-id", help="Resume-safe id; must be a new UUID")
    parser.add_argument(
        "--language", action="append", help="Restrict a diagnostic run to a language code"
    )
    parser.add_argument(
        "--topic-key", action="append", help="Restrict a diagnostic run to a source UUID"
    )
    args = parser.parse_args()
    batch_id = UUID(args.batch_id) if args.batch_id else uuid4()
    policy = __import__("woori.external_policy", fromlist=["status"]).status()
    if not policy["external_calls_allowed"] and not args.skip_collection:
        raise SystemExit("zero-cost external policy blocked collection")
    model = runtime()
    if model["model"] != EXPECTED_MODEL:
        raise SystemExit("Expected existing Qwen3 4B Q4_K_M; no model downloads are allowed")
    if psutil.virtual_memory().available < 2 * 2**30:
        raise SystemExit("Insufficient memory headroom; refusing local inference run")
    with connection() as conn:
        if conn.execute(
            "SELECT 1 FROM article_quality_evaluations WHERE batch_id=%s LIMIT 1", (batch_id,)
        ).fetchone():
            raise SystemExit("Batch ID already has results; choose an unused ID")
        languages = conn.execute(
            "SELECT p.language_code,p.id AS profile_id FROM language_profiles p JOIN languages l ON l.code=p.language_code WHERE l.active AND p.target_country='' ORDER BY CASE p.language_code WHEN 'en' THEN 0 ELSE 1 END,p.language_code"
        ).fetchall()
    if not languages:
        raise SystemExit("No active language profiles")
    if args.language:
        requested = set(args.language)
        languages = [row for row in languages if row["language_code"] in requested]
        if len(languages) != len(requested):
            raise SystemExit("Requested language is not an active DB profile")
    audit(
        "article.batch.started",
        batch_id=str(batch_id),
        model=model["model"],
        language_count=len(languages),
    )
    if not args.skip_collection:
        collect_sources(batch_id)
    sources = reviewed_sources()
    if args.topic_key:
        requested_sources = {UUID(value) for value in args.topic_key}
        sources = [source for source in sources if source["id"] in requested_sources]
        if len(sources) != len(requested_sources):
            raise SystemExit("Requested topic is not a current reviewed source")
    minimum_sources = 1 if args.topic_key else 2
    if len(sources) < minimum_sources:
        raise SystemExit("At least two current reviewed official topics are required")

    outcomes: list[dict[str, object]] = []
    as_of = datetime.now(UTC).date().isoformat()
    for source in sources:
        facts = store_facts(source)
        topic_key = str(source["id"])
        with connection() as conn:
            group_id = conn.execute(
                "INSERT INTO content_groups DEFAULT VALUES RETURNING id"
            ).fetchone()["id"]
        en_version_id = None
        for profile in languages:
            language = str(profile["language_code"])
            started = time.monotonic()
            context = {
                "keyword": source["keyword"],
                "language_code": language,
                "target_country": "",
                "as_of": as_of,
                "localization_policy": "Translate faithfully; retain issuer names and exact financial units; do not infer country-specific rules.",
                "seo_policy": "Informational search intent only; accurate title and concise summary; no ranking guarantee or investment advice.",
                "plan": {
                    "topic": source["keyword"],
                    "category": source["category"],
                    "outline": [
                        "What the official source states",
                        "How to read the reported information",
                        "Limits and source context",
                    ],
                },
                "verified_facts": [
                    {
                        "fact_id": str(fact["id"]),
                        "source_id": str(fact["source_id"]),
                        "text": fact["source_excerpt"],
                    }
                    for fact in facts
                ],
                "sources": [
                    {
                        key: source.get(key)
                        for key in (
                            "id",
                            "url",
                            "evidence",
                            "published_at",
                            "valid_until",
                            "rights",
                        )
                    }
                ],
                "instructions": (
                    "Create a complete, evidence-led informational article that helps a reader understand this specific official release or SEC filing. "
                    "Provide additional explanation of how to interpret the supplied record, but do not add any unsupported economic, company, market, forecast, or investment claim. "
                    "Do not imply independent verification beyond the cited official source. Never invent values, dates, titles, URLs, experiences, quotations, or named entities. "
                    "Do not claim public-record accessibility, legal reuse rights, or define financial terms unless those exact claims occur in the supplied evidence. "
                    "Return only three to five useful search keywords; never make an accession number, CIK, or raw filing date a keyword. "
                    "Paraphrase; do not copy more than 24 consecutive source words. Every factual paragraph must end with the exact [source:SOURCE_ID] marker. "
                    "Use at least three ## sections when the evidence supports them. If the record is too narrow, keep the article concise instead of padding. "
                    "No recommendation to buy, sell, or hold. Keywords and title must match the article and requested language."
                ),
            }
            result: dict[str, object]
            try:
                draft = LlamaCppProvider().generate(
                    context,
                    {
                        "model": EXPECTED_MODEL,
                        "language_verified": False,
                        "evaluation_only": True,
                        "threads": int(model.get("threads", 4)),
                        "timeout_seconds": 120,
                        "max_tokens": 650,
                    },
                )
                quality = evaluate(draft, [source], language, as_of, len(facts))
                metrics = {
                    **draft._metrics,
                    "pipeline_elapsed_ms": round((time.monotonic() - started) * 1000),
                    "source_retrieved_at": str(source["retrieved_at"]),
                    "source_published_at": str(source.get("published_at")),
                    "fact_spans": len(facts),
                    "model_calls": 1,
                    "cpu_model": psutil.cpu_count(logical=False),
                    "available_ram_mib_before": round(psutil.virtual_memory().available / 2**20),
                }
                result = {
                    "draft": draft,
                    "quality": quality,
                    "metrics": metrics,
                    "elapsed_ms": metrics["pipeline_elapsed_ms"],
                    "group_id": group_id,
                    "parent_version_id": en_version_id,
                }
            except (EngineFailure, ValueError, RuntimeError) as exc:
                result = {
                    "draft": None,
                    "quality": {"machine_passed": False},
                    "metrics": {"model": EXPECTED_MODEL},
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "error_category": exc.category
                    if isinstance(exc, EngineFailure)
                    else "article_generation_invalid",
                }
            stored = save_article(batch_id, topic_key, source, facts, language, result)
            if language == "en" and stored.get("version_id"):
                en_version_id = UUID(str(stored["version_id"]))
            outcomes.append(stored)
            print(
                json.dumps(
                    {
                        key: stored.get(key)
                        for key in (
                            "topic_key",
                            "language",
                            "status",
                            "error_category",
                            "elapsed_ms",
                            "ai_calls",
                            "publish_ready",
                        )
                    },
                    ensure_ascii=False,
                )
            )

    artifact = {
        "phase": "3.8-C1",
        "batch_id": str(batch_id),
        "created_at": datetime.now(UTC).isoformat(),
        "model": model,
        "external_collection": not args.skip_collection,
        "source_records": [
            {
                key: source.get(key)
                for key in (
                    "id",
                    "keyword",
                    "category",
                    "url",
                    "source_name",
                    "source_language",
                    "published_at",
                    "retrieved_at",
                    "valid_until",
                    "rights",
                    "access_policy",
                    "evidence",
                )
            }
            for source in sources
        ],
        "results": outcomes,
        "summary": {
            "draft_count": sum(1 for row in outcomes if row.get("version_id")),
            "machine_passed": sum(
                1 for row in outcomes if row.get("status") == "machine_passed_review_required"
            ),
            "quality_held": sum(1 for row in outcomes if row.get("status") == "quality_held"),
            "failed": sum(1 for row in outcomes if row.get("status") == "failed"),
            "all_publish_ready_false": all(not row.get("publish_ready", False) for row in outcomes),
            "human_review_required": True,
            "semantic_accuracy_and_naturalness": "not machine-certified",
        },
    }
    output_name = "P3-8C1-evaluation.json"
    if args.language or args.topic_key:
        output_name = f"P3-8C1-diagnostic-{batch_id}.json"
    output = ROOT / "docs" / "development" / output_name
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    audit(
        "article.batch.completed",
        batch_id=str(batch_id),
        drafts=artifact["summary"]["draft_count"],
        machine_passed=artifact["summary"]["machine_passed"],
        quality_held=artifact["summary"]["quality_held"],
        failed=artifact["summary"]["failed"],
        publish_ready=False,
    )
    print(f"Evaluation artifact: {output.relative_to(ROOT)}")
    print(json.dumps(artifact["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
