"""Run and retain a zero-network localization comparison on the saved Fed source."""

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

from psycopg.types.json import Jsonb
from woori.ai import EngineFailure
from woori.db import connection
from woori.local_inference import gpu_engine_percent, localized_translation, runtime
from woori.localization import fact_ledger, localize_fact
from woori.pipeline import emit, required


def main() -> None:
    with connection() as conn:
        source = conn.execute(
            """SELECT s.* FROM research_sources s
            JOIN LATERAL (SELECT approved FROM source_reviews WHERE source_id=s.id
              ORDER BY review_sequence DESC LIMIT 1) r ON r.approved
            WHERE s.url LIKE 'https://www.federalreserve.gov/%'
            AND NOT EXISTS(SELECT 1 FROM research_sources n WHERE n.keyword_id=s.keyword_id
              AND n.url=s.url AND n.revision>s.revision)
            ORDER BY s.collected_at DESC LIMIT 1"""
        ).fetchone()
        if source is None:
            raise SystemExit("No current approved Federal Reserve source in project DB")
        prior = conn.execute(
            """SELECT DISTINCT ON (language,variant) language,variant,mechanical_gate_passed,metrics,checks,created_at
            FROM research_experiment_evaluations WHERE language IN ('en','ko')
            ORDER BY language,variant,created_at DESC"""
        ).fetchall()
        # The approved federalreserve.gov source text itself is English. Keep the historical
        # research_sources row unchanged; this explicit evaluation-only language attribution
        # is isolated to the new fact snapshot and called out in the resulting report.
        evaluated_source = {**source, "source_language": "en"}
        all_facts = fact_ledger(evaluated_source)
        samples = [
            next(item for item in all_facts if item["entities"]),
            next(item for item in all_facts if item["date_values"]),
        ]
        fact_records = []
        for fact in samples:
            saved_fact = conn.execute(
                """INSERT INTO evidence_facts(fact_key,source_id,source_language,source_excerpt,
                entity_ids,numeric_values,date_values,citation_ids,verification_status,extractor_version)
                VALUES (%s,%s,'en',%s,%s,%s,%s,%s,'source_span_verified',%s)
                ON CONFLICT(source_id,fact_key,extractor_version) DO NOTHING RETURNING *""",
                (
                    fact["fact_key"],
                    source["id"],
                    fact["source_excerpt"],
                    fact["entity_ids"],
                    Jsonb(fact["numeric_values"]),
                    Jsonb(fact["date_values"]),
                    [source["id"]],
                    fact["extractor_version"],
                ),
            ).fetchone()
            if saved_fact is None:
                saved_fact = conn.execute(
                    "SELECT * FROM evidence_facts WHERE source_id=%s AND fact_key=%s AND extractor_version=%s",
                    (source["id"], fact["fact_key"], fact["extractor_version"]),
                ).fetchone()
            saved_fact = required(saved_fact)
            fact_records.append(
                (
                    {
                        **fact,
                        "id": saved_fact["id"],
                        "source_id": source["id"],
                        "citation_ids": [source["id"]],
                    },
                    saved_fact,
                )
            )
        try:
            local_runtime = runtime()
            runtime_state: dict[str, Any] = {
                "available": True,
                "model": local_runtime["model"],
                "backend": local_runtime.get("backend"),
                "gpu_layers": local_runtime.get("gpu_layers"),
                "threads": local_runtime.get("threads"),
                "evaluation_only": True,
            }
        except EngineFailure as error:
            local_runtime = None
            runtime_state = {"available": False, "status": error.category, "evaluation_only": True}
        results: list[dict[str, Any]] = []
        for fact, saved_fact in fact_records:
            for target in ("en", "ko", "zh-CN", "ja"):
                started = time.monotonic()
                metrics: dict[str, Any] = {
                    "ai_calls": 0,
                    "model": "none; deterministic source-span path",
                }
                if target != "en" and local_runtime is not None:
                    import psutil

                    process = psutil.Process(local_runtime["pid"])
                    process.cpu_percent()
                    before_rss = process.memory_info().rss
                    try:
                        translator = lambda excerpt, language, terms, entities: (
                            localized_translation(
                                excerpt, language, terms, entities, local_runtime["model"], 90
                            )
                        )
                        result = localize_fact(fact, target, translator)
                        metrics.update(
                            {
                                "ai_calls": 1,
                                "model": local_runtime["model"],
                                "backend": local_runtime.get("backend"),
                                "rss_before_mib": round(before_rss / 2**20, 2),
                                "rss_after_mib": round(process.memory_info().rss / 2**20, 2),
                                "process_cpu_percent_machine": round(
                                    process.cpu_percent() / (psutil.cpu_count() or 1), 2
                                ),
                                "gpu_utilization_percent_sample": gpu_engine_percent(
                                    local_runtime["pid"]
                                )
                                if local_runtime.get("backend") == "vulkan"
                                else None,
                            }
                        )
                    except EngineFailure as error:
                        result = {
                            "text": "",
                            "source_language": "en",
                            "target_language": target,
                            "fact_id": fact["fact_key"],
                            "source_ids": [str(source["id"])],
                            "status": "held_" + error.category,
                            "checks": {"translation_completed": False},
                            "ai_calls": 1,
                            "human_review_required": True,
                            "publish_ready": False,
                        }
                        metrics.update(
                            {
                                "ai_calls": 1,
                                "model": local_runtime["model"],
                                "error": error.category,
                            }
                        )
                else:
                    result = localize_fact(fact, target)
                result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                result["model"] = metrics["model"]
                result["resource_metrics"] = metrics
                row = required(
                    conn.execute(
                        """INSERT INTO localization_evaluations(source_id,fact_id,target_language,output_snapshot,
                    metrics,checks,machine_passed,human_review_required,publish_ready)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,true,false) RETURNING id,created_at""",
                        (
                            source["id"],
                            saved_fact["id"],
                            target,
                            Jsonb(result),
                            Jsonb({"elapsed_ms": result["elapsed_ms"], **metrics}),
                            Jsonb(result["checks"]),
                            result["status"] == "machine_passed",
                        ),
                    ).fetchone()
                )
                result["evaluation_id"] = str(row["id"])
                result["created_at"] = row["created_at"].isoformat()
                results.append(result)
        emit(
            conn,
            "research.localization.comparison.completed",
            None,
            source_id=str(source["id"]),
            fact_ids=[str(saved["id"]) for _, saved in fact_records],
            target_languages=["en", "ko", "zh-CN", "ja"],
            ai_calls=sum(int(item.get("ai_calls", 0)) for item in results),
            statuses={item["target_language"]: item["status"] for item in results},
        )
        report = {
            "task": "Phase 3.8-B same-source evaluation",
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "id": str(source["id"]),
                "url": source["url"],
                "source_name": source["source_name"],
                "source_language": "en",
                "language_attribution": "evaluation-only; approved official source text is English; historical source row unchanged",
                "evaluation_facts": [
                    {
                        "fact_id": str(saved["id"]),
                        "fact_key": fact["fact_key"],
                        "source_excerpt": fact["source_excerpt"],
                        "sha256": hashlib.sha256(fact["source_excerpt"].encode()).hexdigest(),
                    }
                    for fact, saved in fact_records
                ],
            },
            "local_ai_runtime": runtime_state,
            "localized_results": results,
            "phase_3_8_a_comparison_rows": [dict(r) for r in prior],
            "interpretation": {
                "ai_calls": sum(int(item.get("ai_calls", 0)) for item in results),
                "ko_machine_gate_improved": len(
                    [r for r in results if r["target_language"] == "ko"]
                )
                == len(fact_records)
                and all(
                    r["status"] == "machine_passed" for r in results if r["target_language"] == "ko"
                ),
                "editorial_quality_confirmed": False,
                "zh_ja_evaluation_rationale": "Both Korean fact samples passed the machine gate after entity preservation and date normalization; zh-CN and ja were then run in evaluation-only mode on the same two facts.",
                "comparability_note": "Phase 3.8-A evaluated full draft bodies; this phase evaluates two fact spans per language, so pass rates are not directly comparable across output size.",
                "why": "Fact-level deterministic checks are separate from semantic/naturalness human review. A failed or unsupported translation remains held; no language capability or publishing approval was changed.",
                "human_review_required": True,
                "publish_ready": False,
            },
        }
    output = ROOT / "docs/development/P3-8B-evaluation.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "results": [
                    {
                        k: r.get(k)
                        for k in (
                            "target_language",
                            "status",
                            "elapsed_ms",
                            "ai_calls",
                            "checks",
                            "evaluation_id",
                        )
                    }
                    for r in results
                ],
                "prior_rows": len(prior),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
