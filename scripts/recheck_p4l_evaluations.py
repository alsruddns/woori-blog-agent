"""Append-only deterministic Phase 4-L recheck of the latest stored Fed/SEC drafts."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = "p4l-deterministic-recheck-v2"
sys.path.insert(0, str(ROOT / "services" / "api"))
if not load_dotenv(ROOT / ".env.evaluation", override=True):
    raise SystemExit("evaluation_environment_not_configured")

from woori import pipeline
from woori.ai import Draft
from woori.article_quality import evaluate
from woori.db import connection
from woori.grounding import numbers


def run() -> dict[str, object]:
    batch_id = uuid4()
    started_at = datetime.now(UTC)
    with connection() as conn:
        identity = conn.execute(
            "SELECT current_database() AS database_name,current_user AS role_name"
        ).fetchone()
        if identity is None or identity["database_name"] != "woori_blog_agent_eval":
            raise SystemExit("evaluation_database_identity_mismatch")
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        if controls is None or not pipeline.evaluation_database_isolated(conn, controls):
            raise SystemExit("evaluation_database_isolation_not_confirmed")
        immutable = conn.execute(
            """SELECT c.relname,t.tgenabled FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid
            WHERE c.relname IN ('audit_events','article_quality_evaluations')
              AND NOT t.tgisinternal AND t.tgenabled='O'"""
        ).fetchall()
        immutable_tables = {row["relname"] for row in immutable}
        if not {"audit_events", "article_quality_evaluations"}.issubset(immutable_tables):
            raise SystemExit("append_only_triggers_not_confirmed")
        rows = conn.execute(
            """SELECT DISTINCT ON (j.keyword_id,p.language_code,g.model)
              g.run_id,j.keyword_id,k.keyword,p.language_code,g.model,g.state,
              g.content_version_id,g.result_metadata,g.source_snapshot,r.status AS run_status,r.created_at
            FROM generation_results g
            JOIN generation_jobs j ON j.run_id=g.run_id
            JOIN job_runs r ON r.id=g.run_id
            JOIN language_profiles p ON p.id=g.profile_id
            JOIN keyword_candidates k ON k.id=j.keyword_id
            WHERE j.evaluation_only AND r.created_at >=
              (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')
              AND g.content_version_id IS NOT NULL
              AND (g.source_snapshot::text ILIKE '%%Federal Reserve%%'
                   OR g.source_snapshot::text ILIKE '%%SEC EDGAR%%')
              AND NOT EXISTS (
                SELECT 1 FROM article_quality_evaluations previous
                WHERE previous.content_version_id=g.content_version_id
                  AND previous.language_code=p.language_code
                  AND previous.model=g.model
                  AND previous.prompt_version=%s
              )
            ORDER BY j.keyword_id,p.language_code,g.model,r.created_at DESC""",
            (PROMPT_VERSION,),
        ).fetchall()
        if not rows:
            raise SystemExit("no_current_day_saved_fed_sec_drafts")
        if conn.execute(
            "SELECT 1 FROM job_runs WHERE status IN ('queued','running') LIMIT 1"
        ).fetchone():
            raise SystemExit("evaluation_database_has_active_generation_work")
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('research.p4l.recheck.started',%s)",
            (Jsonb({"batch_id": str(batch_id), "draft_count": len(rows), "ai_calls": 0}),),
        )

    outcomes: list[dict[str, object]] = []
    for row in rows:
        started = time.monotonic()
        version_id = UUID(str(row["content_version_id"]))
        source_snapshot = row["source_snapshot"] or []
        source_ids = [UUID(str(item["id"])) for item in source_snapshot if item.get("id")]
        if not source_ids:
            raise SystemExit(f"source_snapshot_missing_for_run:{row['run_id']}")
        with connection() as conn:
            version = conn.execute(
                "SELECT title,body,created_at FROM content_versions WHERE id=%s", (version_id,)
            ).fetchone()
            facts = conn.execute(
                "SELECT id FROM evidence_facts WHERE source_id=ANY(%s) ORDER BY source_id,fact_key",
                (source_ids,),
            ).fetchall()
        if version is None or not facts:
            raise SystemExit(f"immutable_draft_or_fact_missing_for_run:{row['run_id']}")

        metadata = row["result_metadata"] or {}
        draft = Draft(
            title=str(version["title"]),
            body=str(version["body"]),
            summary=str(metadata.get("summary") or ""),
            keywords=[str(item) for item in metadata.get("keywords", [])],
            source_ids=[str(item) for item in source_ids],
        )
        sources = [dict(item) for item in source_snapshot]
        as_of = version["created_at"].astimezone(UTC).date().isoformat()
        quality = evaluate(draft, sources, str(row["language_code"]), as_of, len(facts))
        evidence_numbers = set(
            numbers(" ".join(str(item.get("evidence", "")) for item in sources) + " " + as_of)
        )
        draft_numbers = set(numbers(f"{draft.title}\n{draft.summary}\n{draft.body}"))
        grounding = quality["grounding_details"]
        details: dict[str, object] = {
            "numeric_values_missing": sorted(evidence_numbers - draft_numbers),
            "numeric_values_added": sorted(draft_numbers - evidence_numbers),
            "proper_name_candidates": grounding.get("proper_name_candidates", []),
            "missing_proper_names": grounding.get("missing_proper_names", []),
            "unsupported_proper_names": grounding.get("unsupported_proper_names", []),
            "source_overlap_words_max": quality["source_overlap_words_max"],
            "source_ids": [str(item) for item in source_ids],
            "fact_ids": [str(item["id"]) for item in facts],
        }
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        machine_passed = bool(quality["machine_passed"])
        status = "machine_passed_review_required" if machine_passed else "quality_held"
        evaluation_id = uuid4()
        metrics = {
            "evaluation_kind": "phase4l_deterministic_recheck",
            "source_run_id": str(row["run_id"]),
            "source_content_version_id": str(version_id),
            "recheck_elapsed_ms": elapsed_ms,
            "ai_calls": 0,
            "model_inference_performed": False,
            "details": details,
        }
        with connection() as conn:
            conn.execute(
                """INSERT INTO article_quality_evaluations
                (id,batch_id,topic_key,topic,language_code,content_version_id,title,source_ids,fact_ids,
                 summary,keywords,model,prompt_version,metrics,checks,machine_passed,human_review_required,
                 error_category,status,publish_ready,elapsed_ms,ai_calls)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,NULL,%s,false,%s,0)""",
                (
                    evaluation_id,
                    batch_id,
                    f"phase4l:{row['run_id']}",
                    str(row["keyword"]),
                    str(row["language_code"]),
                    version_id,
                    draft.title,
                    source_ids,
                    [item["id"] for item in facts],
                    draft.summary,
                    draft.keywords,
                    str(row["model"]),
                    PROMPT_VERSION,
                    Jsonb(metrics),
                    Jsonb(quality["checks"]),
                    machine_passed,
                    status,
                    elapsed_ms,
                ),
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload,language_code) VALUES ('research.p4l.recheck.completed',%s,%s)",
                (
                    Jsonb({
                        "batch_id": str(batch_id),
                        "evaluation_id": str(evaluation_id),
                        "source_run_id": str(row["run_id"]),
                        "source_content_version_id": str(version_id),
                        "language": str(row["language_code"]),
                        "status": status,
                        "failed_checks": [key for key, value in quality["checks"].items() if value is False],
                        "ai_calls": 0,
                        "publish_ready": False,
                    }),
                    str(row["language_code"]),
                ),
            )
        outcomes.append({
            "evaluation_id": str(evaluation_id),
            "source_run_id": str(row["run_id"]),
            "source_content_version_id": str(version_id),
            "topic": str(row["keyword"]),
            "language": str(row["language_code"]),
            "model": str(row["model"]),
            "status": status,
            "machine_passed": machine_passed,
            "checks": quality["checks"],
            "details": details,
            "elapsed_ms": elapsed_ms,
            "ai_calls": 0,
            "human_review_required": True,
            "publish_ready": False,
        })

    passed = sum(item["machine_passed"] is True for item in outcomes)
    artifact: dict[str, object] = {
        "phase": "4-L",
        "kind": "append_only_deterministic_recheck",
        "batch_id": str(batch_id),
        "database": "woori_blog_agent_eval",
        "recorded_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round((datetime.now(UTC) - started_at).total_seconds(), 3),
        "ai_calls": 0,
        "results": outcomes,
        "summary": {
            "drafts_rechecked": len(outcomes),
            "machine_passed_review_required": passed,
            "quality_held": len(outcomes) - passed,
            "human_review_pending": len(outcomes),
            "publish_ready_true": 0,
        },
    }
    output = ROOT / "docs" / "development" / f"P4-L-results-{batch_id}.json"
    if output.exists():
        raise SystemExit("refusing_to_overwrite_phase4l_artifact")
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('research.p4l.batch.completed',%s)",
            (Jsonb({"batch_id": str(batch_id), "artifact": output.name, "summary": artifact["summary"], "publish_ready": False}),),
        )
    return artifact


if __name__ == "__main__":
    print(json.dumps(run()["summary"], ensure_ascii=False))
