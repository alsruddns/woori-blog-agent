"""Append a measured A/B evaluation against an existing research run (no model calls)."""

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "services/api"))

from woori import pipeline
from woori.ai import Draft
from woori.db import connection
from woori.evidence_template import build_evidence_template
from woori.grounding import inspect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    with connection() as conn:
        rows = conn.execute(
            """SELECT v.id AS version_id,v.language,v.title,v.body,g.run_id,g.profile_id,
            g.elapsed_ms,g.provider,g.model,g.result_metadata,g.source_snapshot,k.keyword
            FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id
            JOIN generation_jobs j ON j.run_id=g.run_id
            JOIN keyword_candidates k ON k.id=j.keyword_id
            WHERE g.run_id=%s ORDER BY v.language""",
            (args.run_id,),
        ).fetchall()
    if not {"en", "ko"}.issubset({row["language"] for row in rows}):
        raise SystemExit("Expected existing English and Korean results for the same source run")
    experiment_id = uuid4()
    for row in rows:
        metadata = row["result_metadata"]
        facts = row["source_snapshot"]
        original = Draft(
            title=row["title"], body=row["body"], summary=metadata["summary"],
            keywords=metadata["keywords"], source_ids=metadata["referenced_source_ids"],
        )
        with connection() as conn:
            stage_rows = conn.execute(
                """SELECT stage_name,status,elapsed_ms,validation FROM generation_stage_runs
                WHERE run_id=%s AND profile_id=%s ORDER BY sequence,stage_attempt""",
                (row["run_id"], row["profile_id"]),
            ).fetchall()
        section_stages = [s for s in stage_rows if s["stage_name"] in {"section_generation", "localization"}]
        as_of = row["result_metadata"].get("quality", {}).get("as_of_date")
        if not as_of:
            # The historical body ends with the recorded run date; retain the current audit date
            # only as a comparison input and report that the original date was not persisted.
            from datetime import UTC, datetime

            as_of = datetime.now(UTC).date().isoformat()
        old_checks = inspect(original, facts, row["language"], as_of)
        old_structural = pipeline.quality(original, facts, row["keyword"], False)
        old_gate = bool(old_structural["structural_pass"] and old_checks["rule_pass"])
        old_payload = original.model_dump()
        old_metrics = {
            "elapsed_ms": row["elapsed_ms"],
            "model_calls": len(section_stages),
            "json_schema_valid": True,
            "section_attempts": len(section_stages),
            "section_metrics": metadata.get("metrics", {}).get("section_metrics"),
            "source": "persisted Phase 3.7 execution",
        }
        started = time.perf_counter()
        templated, template_metrics = build_evidence_template(
            facts, row["language"], row["keyword"], as_of
        )
        template_checks = inspect(templated, facts, row["language"], as_of)
        template_structural = pipeline.quality(templated, facts, row["keyword"], False)
        template_gate = bool(template_structural["structural_pass"] and template_checks["rule_pass"])
        template_elapsed = round((time.perf_counter() - started) * 1000)
        entries = [
            ("existing_ai", original, old_payload, old_metrics,
             {"grounding": old_checks, "structure": old_structural,
              "section_failures": [s["validation"] for s in section_stages if s["status"] == "held"]}, old_gate),
        ]
        if row["language"] in {"en", "ko"}:
            entries.append(
                ("evidence_template", templated, templated.model_dump(),
                 {"elapsed_ms": template_elapsed, "model_calls": template_metrics["ai_calls"],
                  "json_schema_valid": True, "fact_count": template_metrics["fact_count"],
                  "source": "deterministic evidence template; no AI calls"},
                 {"grounding": template_checks, "structure": template_structural,
                  "section_failures": []}, template_gate)
            )
        for variant, draft, payload, metrics, checks, passed in entries:
            with connection() as conn:
                conn.execute(
                    """INSERT INTO research_experiment_evaluations
                    (experiment_id,run_id,content_version_id,language,variant,output_snapshot,
                     metrics,checks,mechanical_gate_passed,human_review_required,publish_ready)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,false)""",
                    (experiment_id, row["run_id"], row["version_id"], row["language"], variant,
                     Jsonb(payload), Jsonb(metrics), Jsonb(checks), passed),
                )
                pipeline.emit(
                    conn, "ab_evaluated", row["run_id"], experiment_id=str(experiment_id),
                    content_version_id=str(row["version_id"]), language=row["language"],
                    variant=variant, mechanical_gate_passed=passed,
                    publish_ready=False, model_calls=metrics["model_calls"],
                )
        comparison = {
            "existing_ai": {"elapsed_ms": old_metrics["elapsed_ms"],
                             "model_calls": old_metrics["model_calls"],
                             "gate": old_gate,
                             "failed_grounding": [k for k,v in old_checks["rule_checks"].items() if not v],
                             "failed_structure": [k for k,v in old_structural["checks"].items() if not v]},
            "human_review_required": True, "publish_ready": False,
        }
        if row["language"] in {"en", "ko"}:
            comparison["evidence_template"] = {
                "elapsed_ms": template_elapsed, "model_calls": 0, "gate": template_gate,
                "failed_grounding": [k for k,v in template_checks["rule_checks"].items() if not v],
                "failed_structure": [k for k,v in template_structural["checks"].items() if not v],
            }
        print(json.dumps({
            "experiment_id": str(experiment_id), "language": row["language"],
            **comparison,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
