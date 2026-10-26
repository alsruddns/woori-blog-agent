"""Run exactly one sequential, quota-bound C3 evaluation in the isolated database."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import httpx
import psutil
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env.evaluation", override=True)

from evaluate_complete_articles import reviewed_sources  # type: ignore[import-not-found]
from woori import pipeline
from woori.ai import EngineFailure
from woori.db import connection
from woori.local_inference import auth_headers, runtime

EXPECTED_MODEL = "Qwen3-4B-Q4_K_M.gguf"
SEQUENCE = {"en": 0, "ko": 1, "ja": 2, "zh-CN": 3}
SOURCE_SEQUENCE = {"fed": "fed_rss", "sec": "sec_edgar"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=SOURCE_SEQUENCE, required=True)
    parser.add_argument("--language", choices=SEQUENCE, required=True)
    args = parser.parse_args()
    adapter = SOURCE_SEQUENCE[args.source]
    evaluation_id = uuid4()
    preflight = resource_snapshot()
    if not preflight["resource_gate_passed"]:
        stop("resource_gate_closed", preflight)
    sources = reviewed_sources()
    source = next((item for item in sources if str(item["source_name"]).startswith("Federal Reserve" if adapter == "fed_rss" else "SEC EDGAR")), None)
    if source is None:
        stop("reviewed_source_missing", preflight)
    with connection() as conn:
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        db = conn.execute("SELECT current_database() AS name").fetchone()
        if db is None or db["name"] != "woori_blog_agent_eval":
            stop("physical_evaluation_database_name_mismatch", preflight)
        if controls is None or not pipeline.evaluation_database_isolated(conn, controls):
            stop("physical_evaluation_isolation_failed", preflight)
        if controls["paused"] or not pipeline.resources_ok(controls):
            stop("pipeline_resource_or_pause_gate_closed", preflight)
        if not controls["evaluation_isolated"]:
            stop("evaluation_policy_disabled", preflight)
        if conn.execute("SELECT 1 FROM job_runs WHERE status IN ('queued','running') LIMIT 1").fetchone():
            stop("other_pending_work_in_evaluation_db", preflight)
        profile = conn.execute(
            """SELECT p.id,p.language_code,g.evaluation_daily_limit,g.provider,g.engine,g.enabled
            FROM language_profiles p JOIN languages l ON l.code=p.language_code
            JOIN generation_settings g ON g.profile_id=p.id
            WHERE l.active AND p.target_country='' AND p.language_code=%s""",
            (args.language,),
        ).fetchone()
        if profile is None or not profile["enabled"] or profile["provider"] != "local" or profile["engine"] != "llamacpp":
            stop("target_profile_not_enabled_for_local_inference", preflight)
        assert profile is not None
        quota_row = conn.execute(
            """SELECT count(*)::int AS n FROM generation_targets t
            JOIN generation_jobs j ON j.run_id=t.run_id
            WHERE t.profile_id=%s AND j.evaluation_only
              AND j.created_at >= (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')""",
            (profile["id"],),
        ).fetchone()
        if quota_row is None:
            stop("evaluation_quota_query_failed", preflight)
        used = quota_row["n"]
        if used >= profile["evaluation_daily_limit"]:
            stop("evaluation_quota_exhausted", {**preflight, "quota_used": used, "quota_limit": profile["evaluation_daily_limit"]})

        # Localized SEC evaluations depend on a successful English source draft for
        # this exact SEC keyword. This is a data dependency, not shared quota ordering.
        seed_profile = conn.execute(
            "SELECT p.language_code FROM keyword_candidates k JOIN language_profiles p ON p.id=k.profile_id WHERE k.id=%s",
            (source["keyword_id"],),
        ).fetchone()
        english = conn.execute(
            "SELECT id FROM language_profiles WHERE language_code='en' AND target_country=''"
        ).fetchone()
        if args.language != "en":
            if not english:
                stop("english_source_profile_missing", preflight)
            source_draft = conn.execute(
                """SELECT 1 FROM generation_results g
                JOIN generation_jobs j ON j.run_id=g.run_id
                JOIN job_runs r ON r.id=g.run_id
                WHERE j.keyword_id=%s AND j.evaluation_only AND r.status='succeeded'
                  AND g.profile_id=%s AND g.content_version_id IS NOT NULL LIMIT 1""",
                (source["keyword_id"], english["id"]),
            ).fetchone()
            if not pipeline.evaluation_source_prerequisite_met(
                args.language, bool(source_draft)
            ):
                stop("source_locale_prerequisite_missing", {
                    **preflight,
                    "language": args.language,
                    "prerequisite_language": "en",
                    "english_quota_is_separate": True,
                    "quota_used": used,
                    "quota_limit": profile["evaluation_daily_limit"],
                })
        if seed_profile and seed_profile["language_code"] != "en":
            if not english:
                stop("english_source_profile_missing", preflight)
            conn.execute("UPDATE keyword_candidates SET profile_id=%s WHERE id=%s", (english["id"], source["keyword_id"]))
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('evaluation.seed.profile.normalized',%s)",
                (Jsonb({
                    "keyword_id": str(source["keyword_id"]),
                    "from_language": seed_profile["language_code"],
                    "to_language": "en",
                    "evaluation_id": str(evaluation_id),
                }),),
            )

    model = runtime()
    if model.get("model") != EXPECTED_MODEL or not Path(ROOT / ".local" / EXPECTED_MODEL).is_file():
        stop("expected_existing_local_model_unavailable", preflight)
    with httpx.Client(timeout=3, trust_env=False, headers=auth_headers()) as client:
        if client.get("http://127.0.0.1:11435/health").status_code != 200:
            stop("local_inference_health_failed", preflight)
    loaded_resources = resource_snapshot()
    if not loaded_resources["resource_gate_passed"]:
        stop("resource_gate_closed_after_model_start", loaded_resources)

    key = f"p39t-{args.source}-{args.language}-{evaluation_id.hex}"
    started = time.monotonic()
    try:
        job = pipeline.enqueue(
            source["keyword_id"], key, profile_ids=[profile["id"]],
            evaluation_only=True, evaluation_model=EXPECTED_MODEL,
        )
    except EngineFailure as exc:
        stop("enqueue_failed_" + exc.category, preflight)
    worker_cmd = [
        sys.executable, str(ROOT / "scripts" / "run_evaluation_worker.py"),
        "--evaluation", "--once",
    ]
    worker = subprocess.run(worker_cmd, cwd=ROOT / "services" / "api", timeout=3600, capture_output=True, text=True, check=False)
    elapsed = round(time.monotonic() - started, 2)
    with connection() as conn:
        run = conn.execute("SELECT id,status,error_type,attempts,created_at,updated_at FROM job_runs WHERE id=%s", (job["id"],)).fetchone()
        result = conn.execute(
            """SELECT v.id AS version_id,v.language AS language_code,v.title,v.body,g.state,
              g.elapsed_ms,g.model,g.result_metadata,g.source_snapshot
            FROM generation_results g LEFT JOIN content_versions v ON v.id=g.content_version_id
            WHERE g.run_id=%s""",
            (job["id"],),
        ).fetchone()
        stages = conn.execute(
            """SELECT stage_name,stage_attempt,status,elapsed_ms,error_category,validation,output_snapshot
            FROM generation_stage_runs WHERE run_id=%s ORDER BY sequence""", (job["id"],)
        ).fetchall()
        events = conn.execute(
            "SELECT event_type,created_at,payload FROM audit_events WHERE run_id=%s ORDER BY id", (job["id"],)
        ).fetchall()
        quota_after = conn.execute(
            """SELECT count(*)::int AS n FROM generation_targets t
            JOIN generation_jobs j ON j.run_id=t.run_id
            WHERE t.profile_id=%s AND j.evaluation_only AND j.created_at >=
                (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')""",
            (profile["id"],),
        ).fetchone()
    if not run:
        stop("durable_job_missing_after_worker", preflight)
    metadata = result["result_metadata"] if result else {}
    quality = metadata.get("quality", {}) if isinstance(metadata, dict) else {}
    grounding = quality.get("grounding", {}) if isinstance(quality, dict) else {}
    metrics = metadata.get("metrics", {}) if isinstance(metadata, dict) else {}
    model_samples = metric_samples(metrics)
    token_total = int(sum(numeric(item.get("completion_tokens")) or 0 for item in model_samples))
    model_seconds = sum(numeric(item.get("wall_seconds")) or 0 for item in model_samples)
    rss_values = [
        sample
        for item in model_samples
        if (sample := numeric(item.get("rss_peak_mib"))) is not None
    ]
    manifest = json.loads((ROOT / ".local" / "manifest.json").read_text(encoding="utf-8"))
    model_record = next(item for item in manifest["models"] if item["name"] == EXPECTED_MODEL)
    rss_samples = [
        item["payload"].get("worker_rss_bytes")
        for item in events
        if isinstance(item.get("payload"), dict) and item["payload"].get("worker_rss_bytes")
    ]
    artifact = {
        "phase": "3.9-T",
        "evaluation_id": str(evaluation_id),
        "created_at": datetime.now(UTC).isoformat(),
        "source": {"adapter": adapter, "source_id": str(source["id"]), "source_name": source["source_name"], "url": source["url"], "keyword_id": str(source["keyword_id"])},
        "language": args.language,
        "model": {"name": EXPECTED_MODEL, "runtime": model, "sha256": model_record["sha256"], "license": model_record["license"], "size_bytes": model_record["size_bytes"]},
        "isolation": {"database": "woori_blog_agent_eval", "evaluation_only": True, "worker_exit_code": worker.returncode},
        "quota": {"used_before": used, "used_after": quota_after["n"] if quota_after else None, "limit": profile["evaluation_daily_limit"], "count_policy": "target counted at creation; failures and cancellation remain counted; retries reuse target"},
        "resources": {"before": preflight, "after": resource_snapshot(), "worker_max_rss_bytes_observed_in_job_events": max(rss_samples, default=None), "cpu_percent_during_run_sampled": psutil.cpu_percent(interval=None), "gpu_engine_percent": metrics.get("gpu_engine_percent")},
        "run": dict(run),
        "draft": ({"version_id": str(result["version_id"]) if result["version_id"] else None, "title": result["title"], "body": result["body"], "state": result["state"], "publish_ready": False} if result else None),
        "checks": {"machine_quality_passed": bool(quality.get("structural_pass") and grounding.get("rule_pass") and quality.get("localization_pass", True)), "quality": quality, "grounding": grounding, "human_review_required": True, "publish_ready": False},
        "metrics": {"elapsed_seconds": elapsed, "model_metrics": metrics, "model_call_count": sum(1 for item in model_samples if "completion_tokens" in item) or sum(int(numeric(item.get("model_calls")) or 1) for item in model_samples if "model_calls" in item), "completion_tokens": token_total, "tokens_per_second_aggregate": round(token_total / model_seconds, 2) if model_seconds else None, "rss_peak_mib": max(rss_values, default=None), "process_cpu_mean_percent_machine_samples": [item.get("process_cpu_mean_percent_machine") for item in model_samples if item.get("process_cpu_mean_percent_machine") is not None], "gpu_utilization_percent_samples": [item.get("gpu_utilization_percent") for item in model_samples if item.get("gpu_utilization_percent") is not None], "stage_runs": [dict(item) for item in stages], "audit_event_types": [item["event_type"] for item in events], "worker_process_exit_code": worker.returncode},
        "safety": {"paid_api_calls": 0, "external_data_calls": 0, "blogger_writes": 0, "publish_ready": False},
    }
    out = ROOT / "docs" / "development" / f"P3-9T-run-{args.source}-{args.language}-{evaluation_id}.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(out.relative_to(ROOT)), "source": adapter, "language": args.language, "run_status": run["status"], "machine_quality_passed": artifact["checks"]["machine_quality_passed"], "elapsed_seconds": elapsed, "publish_ready": False}, ensure_ascii=True))
    if worker.returncode != 0 or run["status"] != "succeeded":
        raise SystemExit(1)


def resource_snapshot() -> dict[str, object]:
    disk = psutil.disk_usage(str(ROOT))
    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    return {
        "cpu_percent": cpu,
        "memory_percent": memory.percent,
        "memory_available_bytes": memory.available,
        "disk_free_bytes": disk.free,
        "resource_gate_passed": cpu < 80 and memory.percent < 80 and memory.available >= 6 * 1024**3 and disk.free >= 10 * 1024**3,
    }


def metric_samples(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, dict):
        if "wall_seconds" in value or "completion_tokens" in value or "model_calls" in value:
            found.append(value)
        for item in value.values():
            found.extend(metric_samples(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(metric_samples(item))
    return found


def numeric(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def stop(category: str, evidence: dict[str, object]) -> NoReturn:
    print(json.dumps({"status": "blocked", "error_category": category, "evidence": evidence}, ensure_ascii=True))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
