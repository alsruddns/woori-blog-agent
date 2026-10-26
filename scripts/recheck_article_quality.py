"""Append-only deterministic re-evaluation of previously stored complete articles."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from woori.ai import Draft
from woori.article_quality import evaluate
from woori.db import connection

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BATCH = UUID("accda6bd-cf11-4cdc-8f35-801e0fbbbddc")


def main() -> None:
    batch_id = uuid4()
    with connection() as conn:
        originals = conn.execute(
            "SELECT * FROM article_quality_evaluations WHERE batch_id=%s ORDER BY topic_key,language_code",
            (SOURCE_BATCH,),
        ).fetchall()
    if len(originals) != 8:
        raise SystemExit(f"Expected 8 immutable source evaluations; found {len(originals)}")
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('article.batch.recheck.started',%s)",
            (Jsonb({"batch_id": str(batch_id), "source_batch_id": str(SOURCE_BATCH), "records": len(originals)}),),
        )

    outcomes: list[dict[str, object]] = []
    for original in originals:
        started = time.monotonic()
        source_ids = [UUID(str(value)) for value in original["source_ids"]]
        fact_ids = [UUID(str(value)) for value in original["fact_ids"]]
        checks: dict[str, object]
        details: dict[str, object] = {}
        machine_passed = False
        status = "failed"
        error_category = original["error_category"]
        title = str(original["title"] or "")
        summary = str(original["summary"] or "")
        keywords = list(original["keywords"] or [])
        if original["content_version_id"]:
            with connection() as conn:
                version = conn.execute(
                    "SELECT title,body,created_at FROM content_versions WHERE id=%s",
                    (original["content_version_id"],),
                ).fetchone()
                sources = conn.execute(
                    "SELECT id,url,source_name,evidence,rights,valid_until,published_at FROM research_sources WHERE id=ANY(%s)",
                    (source_ids,),
                ).fetchall()
            if not version or {str(row["id"]) for row in sources} != {str(x) for x in source_ids}:
                raise SystemExit(f"Missing immutable version/source reference for evaluation {original['id']}")
            title = str(version["title"])
            draft = Draft(
                title=title,
                body=version["body"],
                summary=summary,
                keywords=keywords,
                source_ids=[str(value) for value in source_ids],
            )
            quality = evaluate(
                draft,
                [dict(row) for row in sources],
                str(original["language_code"]),
                original["created_at"].astimezone(UTC).date().isoformat(),
                len(fact_ids),
            )
            checks = quality["checks"]
            details = quality["grounding_details"]
            machine_passed = bool(quality["machine_passed"])
            status = "machine_passed_review_required" if machine_passed else "quality_held"
            error_category = None
        else:
            checks = {
                "recheck_possible": False,
                "raw_model_response_available": False,
                "reason": "C1 persisted the sanitized schema error but not its response body; original cannot be replayed",
                "original_error_category": error_category,
            }
            error_category = "prior_generation_failed_not_replayable"

        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        metrics = {
            "evaluation_kind": "deterministic_recheck",
            "source_batch_id": str(SOURCE_BATCH),
            "source_evaluation_id": str(original["id"]),
            "source_content_version_id": str(original["content_version_id"] or ""),
            "recheck_elapsed_ms": elapsed_ms,
            "ai_calls": 0,
            "details": details,
        }
        with connection() as conn:
            row = conn.execute(
                """INSERT INTO article_quality_evaluations
                (batch_id,topic_key,topic,language_code,content_version_id,title,source_ids,fact_ids,
                 summary,keywords,model,prompt_version,metrics,checks,machine_passed,human_review_required,
                 error_category,status,publish_ready,elapsed_ms,ai_calls)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'p3.8-c2-deterministic-recheck-v1',
                 %s,%s,%s,true,%s,%s,false,%s,0) RETURNING id""",
                (
                    batch_id, original["topic_key"], original["topic"], original["language_code"],
                    original["content_version_id"], title, source_ids, fact_ids, summary, keywords,
                    original["model"], Jsonb(metrics), Jsonb(checks), machine_passed,
                    error_category, status, elapsed_ms,
                ),
            ).fetchone()
            conn.execute(
                "INSERT INTO audit_events(event_type,payload,language_code) VALUES ('article.quality.rechecked',%s,%s)",
                (Jsonb({"batch_id": str(batch_id), "source_batch_id": str(SOURCE_BATCH),
                        "source_evaluation_id": str(original["id"]), "new_evaluation_id": str(row["id"]),
                        "language": original["language_code"], "status": status,
                        "failed_checks": [key for key, value in checks.items() if value is False],
                        "publish_ready": False}), original["language_code"]),
            )
        outcomes.append({
            "source_evaluation_id": str(original["id"]), "evaluation_id": str(row["id"]),
            "topic_key": str(original["topic_key"]), "language": original["language_code"],
            "title": title, "source_content_version_id": str(original["content_version_id"] or ""),
            "status": status, "error_category": error_category, "checks": checks,
            "details": details, "elapsed_ms": elapsed_ms, "ai_calls": 0, "publish_ready": False,
        })
        print(json.dumps(outcomes[-1], ensure_ascii=True))

    artifact = {
        "phase": "3.8-C2",
        "kind": "append_only_deterministic_recheck",
        "batch_id": str(batch_id),
        "source_batch_id": str(SOURCE_BATCH),
        "created_at": datetime.now(UTC).isoformat(),
        "results": outcomes,
        "summary": {
            "rechecked": len(outcomes),
            "machine_passed": sum(1 for item in outcomes if item["status"] == "machine_passed_review_required"),
            "quality_held": sum(1 for item in outcomes if item["status"] == "quality_held"),
            "not_replayable": sum(1 for item in outcomes if item["status"] == "failed"),
            "all_publish_ready_false": all(not item["publish_ready"] for item in outcomes),
        },
    }
    output = ROOT / "docs" / "development" / "P3-8C2-regression.json"
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing recheck artifact")
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('article.batch.recheck.completed',%s)",
            (Jsonb({"batch_id": str(batch_id), "source_batch_id": str(SOURCE_BATCH),
                    "rechecked": len(outcomes), "summary": artifact["summary"], "publish_ready": False}),),
        )
    print(f"Evaluation artifact: {output.relative_to(ROOT)}")
    print(json.dumps(artifact["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
