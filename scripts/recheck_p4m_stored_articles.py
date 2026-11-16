"""Recheck the preserved Phase 4-L sample deterministically without DB writes or inference."""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.ai import Draft
from woori.article_quality import evaluate


def longest_overlap_phrase(body: str, source_text: str) -> str:
    def tokens(value: str) -> list[str]:
        return re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", value.casefold())

    left, right = tokens(body), tokens(source_text)
    longest: list[str] = []
    for start in range(len(right)):
        for body_start in range(len(left)):
            run: list[str] = []
            while start + len(run) < len(right) and body_start + len(run) < len(left):
                if right[start + len(run)] != left[body_start + len(run)]:
                    break
                run.append(right[start + len(run)])
            if len(run) > len(longest):
                longest = run
    return " ".join(longest)


def main() -> None:
    import psycopg
    from psycopg.rows import dict_row

    baseline_path = ROOT / "docs/development/P4-L-results-448d6fa9-c87d-4038-b97d-04727b612dbd.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    result_ids = [item["evaluation_id"] for item in baseline["results"]]
    dsn = None
    for filename in (".env.evaluation-readonly", ".env.evaluation", ".env"):
        path = ROOT / filename
        if not path.exists():
            continue
        values = dotenv_values(path)
        dsn = values.get("EVALUATION_DATABASE_URL")
        if dsn:
            break
    if not dsn:
        raise SystemExit("Evaluation read-only connection is not configured")

    with psycopg.connect(dsn, connect_timeout=4, row_factory=dict_row) as conn:
        identity = conn.execute(
            "SELECT current_database() AS database_name,current_user AS role_name"
        ).fetchone()
        if not identity or identity["database_name"] != "woori_blog_agent_eval" or identity["role_name"] != "woori_eval_reader":
            raise SystemExit("Read-only evaluation database identity check failed")
        rows = conn.execute(
            """SELECT q.id AS evaluation_id,q.topic_key,q.topic,q.language_code,q.title,
                q.summary,q.keywords,q.source_ids,q.fact_ids,q.model,q.prompt_version,q.metrics,q.checks,
                q.machine_passed,q.created_at,v.id AS content_version_id,v.version,v.body,v.created_at AS version_created_at
            FROM article_quality_evaluations q JOIN content_versions v
                ON v.id=q.content_version_id WHERE q.id=ANY(%s)""",
            (result_ids,),
        ).fetchall()
        if len(rows) != len(result_ids):
            raise SystemExit("Stored Phase 4-L sample is incomplete; no evaluation was written")
        output: dict[str, Any] = {
            "phase": "4-M",
            "kind": "deterministic_readonly_recheck",
            "batch_id": str(uuid.uuid4()),
            "baseline_artifact": baseline_path.name,
            "database": identity["database_name"],
            "database_role": identity["role_name"],
            "recorded_at": datetime.now(UTC).isoformat(),
            "model_inference": False,
            "database_writes": False,
            "results": [],
        }
        for row in rows:
            sources = conn.execute(
                """SELECT id,source_name,url,published_at,collected_at,evidence,rights,
                    access_policy,valid_until,revision,source_language
                FROM research_sources WHERE id=ANY(%s) ORDER BY id""",
                (row["source_ids"],),
            ).fetchall()
            facts = conn.execute(
                """SELECT id,fact_key,source_id,source_language,source_excerpt,entity_ids,
                    numeric_values,date_values,citation_ids,verification_status
                FROM evidence_facts WHERE id=ANY(%s) ORDER BY fact_key,id""",
                (row["fact_ids"],),
            ).fetchall()
            source_rows = [dict(source) for source in sources]
            fact_rows = [dict(fact) for fact in facts]
            draft = Draft(
                title=row["title"], body=row["body"], summary=row["summary"],
                keywords=list(row["keywords"] or []),
                source_ids=[str(source_id) for source_id in row["source_ids"]],
            )
            checked = evaluate(
                draft, source_rows, row["language_code"],
                row["version_created_at"].astimezone(UTC).date().isoformat(), len(fact_rows),
            )
            previous_checks = row["checks"] or {}
            if "checks" in previous_checks and isinstance(previous_checks["checks"], dict):
                previous_checks = previous_checks["checks"]
            current_checks = checked["checks"]
            failed = [key for key, value in current_checks.items() if value is False]
            body = row["body"] or ""
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
            baseline_row = next(item for item in baseline["results"] if item["evaluation_id"] == str(row["evaluation_id"]))
            result: dict[str, Any] = {
                "evaluation_id": str(row["evaluation_id"]),
                "content_version_id": str(row["content_version_id"]),
                "content_version": row["version"],
                "topic_key": row["topic_key"], "topic": row["topic"],
                "language": row["language_code"], "model": row["model"],
                "prompt_version": row["prompt_version"],
                "title": row["title"], "keywords": list(row["keywords"] or []),
                "stored_status": baseline_row["status"],
                "stored_machine_passed": baseline_row["machine_passed"],
                "stored_failed_checks": [k for k, v in baseline_row["checks"].items() if v is False],
                "rechecked_status": "machine_checked_review_required" if checked["machine_passed"] else "quality_held",
                "rechecked_machine_passed": checked["machine_passed"],
                "rechecked_failed_checks": failed,
                "checks_before": {k: previous_checks.get(k) for k in current_checks},
                "checks_after": current_checks,
                "metrics": {
                    "body_characters": len(body), "body_whitespace_words": len(body.split()),
                    "paragraph_count": len(paragraphs), "heading_count": checked["section_count"],
                    "fact_count": len(fact_rows), "source_overlap_words_max": checked["source_overlap_words_max"],
                    "stored_generation_metrics": row["metrics"],
                },
                "failure_evidence": {
                    "proper_name_candidates": checked.get("grounding_details", {}).get("proper_name_candidates", []),
                    "unsupported_proper_names": checked.get("grounding_details", {}).get("unsupported_proper_names", []),
                    "unexpected_numbers": checked.get("grounding_details", {}).get("unexpected_numbers", []),
                    "numeric_values_missing": checked.get("grounding_details", {}).get("numeric_values_missing", []),
                    "numeric_values_added": checked.get("grounding_details", {}).get("numeric_values_added", []),
                    "source_excerpt_previews": [str(source["evidence"])[:500] for source in source_rows],
                    "paragraph_previews": [p[:300] for p in paragraphs[:4]],
                    "longest_shared_source_token_run": max(
                        (longest_overlap_phrase(body, str(source.get("evidence", ""))) for source in source_rows),
                        key=lambda value: len(value.split()), default="",
                    ),
                },
                "human_review_required": True,
                "publish_ready": False,
            }
            output["results"].append(result)

    output["summary"] = {
        "sample_count": len(output["results"]),
        "stored_machine_passed": sum(bool(item["stored_machine_passed"]) for item in output["results"]),
        "rechecked_machine_passed": sum(bool(item["rechecked_machine_passed"]) for item in output["results"]),
        "quality_held": sum(not bool(item["rechecked_machine_passed"]) for item in output["results"]),
        "model_inference_count": 0,
        "quota_used": 0,
    }
    output["failure_classification"] = [
        {
            "check": "keywords_are_search_terms_not_internal_ids",
            "stored_failures": 5,
            "classification": "validator_false_positive",
            "evidence": "All five rejected keyword examples were date-bearing SEC filing queries; the old rule treated ISO dates as internal identifiers.",
            "change": "Reject UUID and explicit pipeline/source/fact IDs, while preserving legitimate dates.",
            "reproduced_by_test": "test_article_gate_allows_date_search_terms_but_holds_internal_ids",
        },
        {
            "check": "no_unsupported_proper_names",
            "stored_failures": 4,
            "classification": "validator_false_positive_in_all_four_samples",
            "evidence": "The entity recognizer formed `Q Apple Inc` from the `10-Q` filing label; two Japanese outputs rendered source-backed USD as United States Dollar, which the proper-name-only rule miscategorized.",
            "change": "Treat the post-hyphen Q as a form label and accept the United States Dollar alias only when the cited source explicitly contains USD/U.S. dollars.",
            "reproduced_by_tests": ["test_english_name_after_form_hyphen_is_not_a_spurious_name", "test_supported_currency_code_does_not_trigger_unsupported_proper_name"],
        },
        {
            "check": "no_mass_direct_quote",
            "stored_failures": 1,
            "classification": "actual_model_output_error; quality_hold_retained",
            "evidence": "The Fed English output repeats a 28-word source run: `the Federal Reserve Board on Tuesday released the minutes from its recent meetings to review and determine the discount rates provided to depository institutions through the discount window`.",
            "automatic_rewrite": False,
            "human_review_required": True,
        },
        {
            "check": "language_metadata_matches",
            "stored_failures": 1,
            "classification": "actual_localization_output_error; quality_hold_retained",
            "evidence": "The SEC Korean draft title/keyword remains `Apple Inc. 10-Q filed 2026-07-31`; its core phrase is English despite a Korean title prefix and Korean body.",
            "automatic_rewrite": False,
            "human_review_required": True,
        },
    ]
    output["content_volume_assessment"] = {
        "character_count_unit": "Unicode code points in saved body text",
        "body_characters_min": min(item["metrics"]["body_characters"] for item in output["results"]),
        "body_characters_max": max(item["metrics"]["body_characters"] for item in output["results"]),
        "body_characters_mean": round(sum(item["metrics"]["body_characters"] for item in output["results"]) / len(output["results"]), 1),
        "paragraphs_min": min(item["metrics"]["paragraph_count"] for item in output["results"]),
        "paragraphs_max": max(item["metrics"]["paragraph_count"] for item in output["results"]),
        "interpretation": "These are short source-grounded briefs (one Fed source with five facts; one SEC filing with four facts), not evidence of full-length blog quality. Semantic accuracy, naturalness, rights, and reader value still need human review.",
        "generation_token_measurement": "The one SEC-ko Phase 4-L inference artifact reports 256 completion tokens across five calls (outline plus four fact-localization calls); this is aggregate pipeline output, not a body-only token count.",
    }
    output["prompt_and_glossary_analysis"] = {
        "evaluation_prompt_version_field": "p4l-deterministic-recheck-v2 identifies the evaluation rule set, not the original generation prompt.",
        "generation_snapshot_source": "generation_results.prompt_snapshot was present for the quoted Fed article.",
        "explicit_quote_guard_terms_in_snapshot": {
            "verbatim": False, "paraphrase": False, "do_not_copy": False,
            "do_not_quote": False, "direct_quotation": False,
        },
        "glossary_matches_for_usd_and_named_entities": 0,
        "glossary_effect": "No approved glossary mapping explains the stored USD expansion. The checker was corrected to treat USD as evidence for its currency alias only when the source contains that code; editorial fluency remains a human check.",
    }
    name = f"P4-M-results-{output['batch_id']}.json"
    target = ROOT / "docs/development" / name
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str) + "\n",encoding="utf-8")
    print(json.dumps({"artifact": name, "summary": output["summary"], "languages": {
        language: {
            "sample_count": sum(item["language"] == language for item in output["results"]),
            "stored_passed": sum(item["language"] == language and item["stored_machine_passed"] for item in output["results"]),
            "rechecked_passed": sum(item["language"] == language and item["rechecked_machine_passed"] for item in output["results"]),
            "failures": sorted({check for item in output["results"] if item["language"] == language for check in item["rechecked_failed_checks"]}),
        } for language in sorted({item["language"] for item in output["results"]})
    }},ensure_ascii=False))


if __name__ == "__main__":
    main()
