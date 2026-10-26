"""Run two bounded local-only fact-first pipeline evaluations into internal drafts."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_complete_articles import reviewed_sources
from woori import pipeline
from woori.db import connection
from woori.local_inference import runtime

MODEL = "Qwen3-4B-Q4_K_M.gguf"
LANGUAGES = {"en", "ko", "zh-CN", "ja"}
RETRYABLE_JOB_ERRORS = {
    "local_engine_unavailable", "local_model_timeout", "worker_interrupted",
    "lease_expired", "fact_render_contract_marker_invalid",
}


def main() -> None:
    sources = reviewed_sources()
    if len(sources) != 2:
        raise SystemExit("Expected the two current reviewed Federal Reserve and SEC sources")
    with connection() as conn:
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        if not controls or controls["paused"] or not controls["evaluation_isolated"]:
            raise SystemExit("Pipeline is paused or evaluation database isolation is not confirmed")
        quota_rows = conn.execute(
            """SELECT p.language_code,count(t.run_id) AS target_count,g.evaluation_daily_limit AS daily_limit
            FROM language_profiles p JOIN languages l ON l.code=p.language_code AND l.active
            JOIN generation_settings g ON g.profile_id=p.id
            LEFT JOIN generation_targets t ON t.profile_id=p.id
            LEFT JOIN generation_jobs j ON j.run_id=t.run_id AND j.created_at>=(date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')
                AND j.evaluation_only
            WHERE p.target_country='' AND (t.run_id IS NULL OR j.run_id IS NOT NULL)
            GROUP BY p.language_code,g.evaluation_daily_limit ORDER BY p.language_code"""
        ).fetchall()
        insufficient = [
            row for row in quota_rows
            if not pipeline.daily_batch_capacity_available(
                int(row["target_count"]), int(row["daily_limit"]), len(sources)
            )
        ]
        if insufficient:
            raise SystemExit("Daily quota cannot fit the complete two-source batch; no job was enqueued")
        if not pipeline.resources_ok(controls):
            raise SystemExit("Pipeline resource gate is closed; no evaluation resumed")
    model = runtime()
    if model["model"] != MODEL:
        raise SystemExit("Expected already installed Qwen3 4B Q4_K_M; downloads are disabled")
    by_source = {str(source["id"]): source for source in sources}
    batch_id = uuid4()
    jobs = []
    with connection() as conn:
        profiles = conn.execute(
            """SELECT p.language_code FROM language_profiles p JOIN languages l ON l.code=p.language_code
            WHERE l.active AND p.target_country='' ORDER BY CASE p.language_code WHEN 'en' THEN 0 ELSE 1 END,p.language_code"""
        ).fetchall()
        active_languages = {str(row["language_code"]) for row in profiles}
        if active_languages != LANGUAGES:
            raise SystemExit("The active base language profiles differ from the requested four-language evaluation")
        if conn.execute("SELECT 1 FROM pipeline_controls WHERE paused").fetchone():
            raise SystemExit("Pipeline is paused; no evaluation queued")
        existing = conn.execute(
            """SELECT r.id,r.status,r.attempts,r.error_type,r.idempotency_key,j.paused
            FROM job_runs r JOIN generation_jobs j ON j.run_id=r.id
            WHERE r.idempotency_key LIKE 'p38c3-%' ORDER BY r.created_at DESC"""
        ).fetchall()
        open_batch: dict[str, dict[str, object]] = {}
        open_batch_id = None
        for row in existing:
            parts = str(row["idempotency_key"]).split("-", 2)
            if len(parts) != 3:
                continue
            candidate = parts[1]
            if open_batch_id is None:
                open_batch_id = candidate
            if candidate == open_batch_id and parts[2] in by_source:
                open_batch[parts[2]] = dict(row)
        if open_batch_id and set(open_batch) == set(by_source):
            batch_id = UUID(hex=open_batch_id)
            own_ids = {str(row["id"]) for row in open_batch.values()}
            other_pending = conn.execute(
                "SELECT count(*) AS n FROM job_runs WHERE task_kind='content' AND status IN ('queued','running') AND id<>ALL(%s)",
                (list(own_ids),),
            ).fetchone()["n"]
            if other_pending:
                raise SystemExit("Other content jobs are queued or running; refusing to consume unrelated work")
            for source_id, row in open_batch.items():
                source = by_source[source_id]
                if row["status"] == "failed":
                    if int(row["attempts"]) < 2 and row["error_type"] in RETRYABLE_JOB_ERRORS:
                        conn.execute(
                            "UPDATE job_runs SET status='queued',available_at=now(),updated_at=now() WHERE id=%s",
                            (row["id"],),
                        )
                        conn.execute("UPDATE generation_jobs SET paused=false WHERE run_id=%s", (row["id"],))
                        pipeline.emit(conn, "job.retry", row["id"], reason="bounded fact-first evaluation retry")
                        conn.execute(
                            "INSERT INTO generation_attempts(run_id,attempt,event,error_category) VALUES (%s,%s,'retry',%s)",
                            (row["id"], int(row["attempts"]) + 1, row["error_type"]),
                        )
                elif row["status"] == "queued" and row["paused"]:
                    conn.execute("UPDATE generation_jobs SET paused=false WHERE run_id=%s", (row["id"],))
                    pipeline.emit(conn, "job.resume", row["id"], reason="fact-first evaluation resumed")
                jobs.append({"run_id": str(row["id"]), "source_id": source_id, "title": source["source_name"]})
        else:
            if conn.execute("SELECT count(*) AS n FROM job_runs WHERE task_kind='content' AND status IN ('queued','running')").fetchone()["n"]:
                raise SystemExit("Other content jobs are queued or running; refusing to consume unrelated work")
            for source in sources:
                if source.get("source_language") != "en" or not source.get("keyword_id"):
                    raise SystemExit("Source is not a reviewed English record linked to a keyword")
                job = pipeline.enqueue(
                    source["keyword_id"],
                    f"p38c3-{batch_id.hex}-{source['id']}",
                    evaluation_only=True,
                    evaluation_model=MODEL,
                )
                jobs.append({"run_id": str(job["id"]), "source_id": str(source["id"]), "title": source["source_name"]})
    if len(jobs) != 2:
        raise SystemExit("Existing evaluation is terminal or incomplete; inspect durable job state before starting new work")
    started = time.monotonic()
    deadline = started + 3600
    while time.monotonic() < deadline:
        with connection() as conn:
            states = conn.execute(
                "SELECT id,status,error_type,attempts FROM job_runs WHERE id=ANY(%s)",
                ([job["run_id"] for job in jobs],),
            ).fetchall()
        if states and all(row["status"] in ("succeeded", "failed") for row in states):
            retryable = [
                row for row in states
                if row["status"] == "failed" and int(row["attempts"]) < 2
                and row["error_type"] in RETRYABLE_JOB_ERRORS
            ]
            if retryable:
                with connection() as conn:
                    for row in retryable:
                        conn.execute("UPDATE job_runs SET status='queued',available_at=now(),updated_at=now() WHERE id=%s", (row["id"],))
                        pipeline.emit(conn, "job.retry", row["id"], reason="single bounded C3 evaluation retry")
                        conn.execute(
                            "INSERT INTO generation_attempts(run_id,attempt,event,error_category) VALUES (%s,%s,'retry',%s)",
                            (row["id"], int(row["attempts"]) + 1, row["error_type"]),
                        )
                continue
            break
        if not pipeline.tick(evaluation_only=True):
            time.sleep(3)
    else:
        raise SystemExit("Bounded 60-minute evaluation window elapsed; durable jobs were left for recovery")

    outputs = []
    with connection() as conn:
        for job in jobs:
            run_id = job["run_id"]
            run = conn.execute("SELECT status,error_type,attempts FROM job_runs WHERE id=%s", (run_id,)).fetchone()
            rows = conn.execute(
                """SELECT p.language_code,v.id AS version_id,v.title,v.body,g.state,g.elapsed_ms,g.result_metadata
                FROM generation_results g JOIN language_profiles p ON p.id=g.profile_id
                LEFT JOIN content_versions v ON v.id=g.content_version_id WHERE g.run_id=%s ORDER BY p.language_code""",
                (run_id,),
            ).fetchall()
            stage_rows = conn.execute(
                """SELECT stage_name,status,count(*) AS n,coalesce(sum(elapsed_ms),0) AS elapsed_ms
                FROM generation_stage_runs WHERE run_id=%s GROUP BY stage_name,status ORDER BY stage_name,status""",
                (run_id,),
            ).fetchall()
            outputs.append({
                **job,
                "run_status": run["status"], "error_category": run["error_type"], "attempts": run["attempts"],
                "results": [{
                    "language": row["language_code"], "content_version_id": str(row["version_id"]) if row["version_id"] else None,
                    "title": row["title"], "body": row["body"], "state": row["state"],
                    "publish_ready": False, "elapsed_ms": row["elapsed_ms"],
                    "machine_quality_passed": bool(
                        (row["result_metadata"] or {}).get("quality", {}).get("structural_pass")
                        and (row["result_metadata"] or {}).get("quality", {}).get("grounding", {}).get("rule_pass")
                        and (row["result_metadata"] or {}).get("quality", {}).get("localization_pass", True)
                    ),
                    "metadata": row["result_metadata"],
                } for row in rows],
                "stage_summary": [dict(stage) for stage in stage_rows],
            })
    artifact = {
        "phase": "3.8-C3", "batch_id": str(batch_id), "created_at": datetime.now(UTC).isoformat(),
        "model": model, "external_collection": False, "paid_calls": 0, "blogger_writes": 0,
        "elapsed_seconds": round(time.monotonic() - started, 2), "jobs": outputs,
        "summary": {
            "expected_drafts": 8,
            "saved_drafts": sum(len(job["results"]) for job in outputs),
            "machine_passed": sum(1 for job in outputs for item in job["results"] if item["machine_quality_passed"]),
            "quality_held": sum(1 for job in outputs for item in job["results"] if item["state"] == "quality_held"),
            "failed_runs": sum(1 for job in outputs if job["run_status"] == "failed"),
            "all_publish_ready_false": all(not item["publish_ready"] for job in outputs for item in job["results"]),
            "human_semantic_review_required": True,
        },
    }
    out = ROOT / "docs" / "development" / f"P3-8C3-evaluation-{batch_id}.json"
    if out.exists():
        raise SystemExit("Evaluation artifact already exists; append a new batch instead of overwriting")
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(out.relative_to(ROOT)), "summary": artifact["summary"], "elapsed_seconds": artifact["elapsed_seconds"]}, ensure_ascii=True))
    if artifact["summary"]["saved_drafts"] != 8 or not artifact["summary"]["all_publish_ready_false"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
