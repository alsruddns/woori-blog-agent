"""Append a deterministic, no-model quality recheck of one isolated C3 draft."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if not load_dotenv(ROOT / ".env.evaluation", override=True):
    raise SystemExit("Evaluation DB configuration is required")
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori import article_quality
from woori.ai import Draft
from woori.db import connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=UUID, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    batch_id = uuid4()

    with connection() as conn:
        database = conn.execute("SELECT current_database() AS db").fetchone()
        if database is None or database["db"] != "woori_blog_agent_eval":
            raise SystemExit("Refusing to recheck outside the isolated evaluation database")
        saved = conn.execute(
            """SELECT r.id,r.status,j.evaluation_only,g.id AS result_id,g.profile_id,
                g.model,g.result_metadata,g.source_snapshot,v.id AS version_id,v.title,v.body
            FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
            JOIN generation_results g ON g.run_id=r.id
            JOIN content_versions v ON v.id=g.content_version_id
            WHERE r.id=%s ORDER BY g.created_at DESC LIMIT 1""",
            (args.run_id,),
        ).fetchone()
        if saved is None:
            raise SystemExit("Saved evaluation draft was not found")
        if not saved["evaluation_only"] or saved["status"] != "succeeded":
            raise SystemExit("Only a saved, successful evaluation-only draft can be rechecked")
        metadata = saved["result_metadata"]
        source_snapshot = saved["source_snapshot"]
        if not isinstance(source_snapshot, list) or not source_snapshot:
            raise SystemExit("Saved source snapshot is missing")
        source_ids = [UUID(str(source["id"])) for source in source_snapshot]
        source_rows = conn.execute(
            "SELECT id,source_name,url,evidence,rights,source_language,collected_at,valid_until,revision FROM research_sources WHERE id=ANY(%s)",
            (source_ids,),
        ).fetchall()
        if {str(row["id"]) for row in source_rows} != {str(value) for value in source_ids}:
            raise SystemExit("A cited source is no longer present; no evaluation was written")
        facts = metadata.get("metrics", {}).get("fact_registry", [])
        fact_ids = [UUID(str(fact["registry_id"])) for fact in facts if fact.get("registry_id")]
        if not fact_ids:
            raise SystemExit("Saved fact registry is missing")
        profile = conn.execute(
            "SELECT language_code,target_country FROM language_profiles WHERE id=%s",
            (saved["profile_id"],),
        ).fetchone()
        if profile is None:
            raise SystemExit("Saved language profile is missing")

        draft = Draft(
            title=saved["title"], body=saved["body"],
            summary=metadata.get("summary", ""),
            keywords=metadata.get("keywords", []),
            source_ids=[str(value) for value in source_ids],
        )
        quality_started = time.monotonic()
        result = article_quality.evaluate(
            draft,
            [dict(row) for row in source_rows],
            profile["language_code"],
            datetime.now(UTC).date().isoformat(),
            len(facts),
        )
        elapsed_ms = round((time.monotonic() - quality_started) * 1000)
        passed = bool(result["machine_passed"])
        failed_rules = sorted(key for key, value in result["checks"].items() if value is False)
        source_name = str(source_rows[0]["source_name"])
        conn.execute(
            """INSERT INTO article_quality_evaluations
            (batch_id,topic_key,topic,language_code,content_version_id,title,source_ids,fact_ids,
             summary,model,prompt_version,metrics,checks,machine_passed,human_review_required,
             error_category,status,publish_ready,elapsed_ms,ai_calls,keywords)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,false,%s,0,%s)""",
            (
                batch_id, f"phase39t:{args.run_id}", source_name,
                profile["language_code"], saved["version_id"], saved["title"],
                source_ids, fact_ids, metadata.get("summary", ""), saved["model"],
                "p39u-article-quality-v1",
                Jsonb({
                    "mode": "deterministic_saved_draft_recheck",
                    "model_calls": 0,
                    "elapsed_ms": elapsed_ms,
                    "total_elapsed_ms": round((time.monotonic() - started) * 1000),
                    "source_revisions": [row["revision"] for row in source_rows],
                    "previous_generation_state": "quality_held",
                    "target_country": profile["target_country"],
                }),
                Jsonb(result), passed,
                None if passed else ",".join(failed_rules) or "article_quality_gate_failed",
                "machine_passed_review_required" if passed else "quality_held",
                elapsed_ms, metadata.get("keywords", []),
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,run_id,language_code,payload) VALUES ('research.article_quality.rechecked',%s,%s,%s)",
            (
                args.run_id, profile["language_code"],
                Jsonb({
                    "batch_id": str(batch_id),
                    "content_version_id": str(saved["version_id"]),
                    "evaluation_only": True,
                    "machine_passed": passed,
                    "failed_rules": failed_rules,
                    "model_calls": 0,
                }),
            ),
        )

    print(json.dumps({
        "batch_id": str(batch_id), "run_id": str(args.run_id),
        "content_version_id": str(saved["version_id"]),
        "machine_passed": passed, "failed_rules": failed_rules,
        "source_overlap_words_max": result["source_overlap_words_max"],
        "human_review_required": True, "publish_ready": False,
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
