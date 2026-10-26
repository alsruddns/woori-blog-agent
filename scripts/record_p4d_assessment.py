"""Record Phase 4-D readiness evidence without external calls or model execution."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psutil
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori import pipeline
from woori.config import settings
from woori.db import connection
from woori.external_policy import status as external_status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-name", default=None)
    args = parser.parse_args()
    captured = datetime.now(ZoneInfo("Asia/Seoul"))
    output_name = args.output_name or f"P4-D-evaluation-{captured:%Y%m%d}.json"
    if Path(output_name).name != output_name or not output_name.endswith(".json"):
        raise SystemExit("Output must be a JSON filename under docs/development")
    output = ROOT / "docs" / "development" / output_name
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing artifact: {output.name}")

    load_dotenv(ROOT / ".env.evaluation", override=True)
    settings.cache_clear()
    with connection() as conn:
        identity = conn.execute("SELECT current_database() AS name").fetchone()
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        if not identity or identity["name"] != "woori_blog_agent_eval":
            raise SystemExit("Refusing evaluation snapshot outside isolated evaluation DB")
        if not controls or not pipeline.evaluation_database_isolated(conn, controls):
            raise SystemExit("Evaluation DB isolation check failed")
        evaluation_database_name = identity["name"]
        quota = conn.execute(
            """SELECT p.language_code,g.evaluation_daily_limit AS quota_limit,
                count(*) FILTER (WHERE j.evaluation_only)::int AS quota_used,
                (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') + interval '1 day') AT TIME ZONE 'Asia/Seoul' AS resets_at
            FROM language_profiles p JOIN languages l ON l.code=p.language_code AND l.active
            JOIN generation_settings g ON g.profile_id=p.id
            LEFT JOIN generation_targets t ON t.profile_id=p.id
            LEFT JOIN generation_jobs j ON j.run_id=t.run_id AND j.evaluation_only
                AND j.created_at >= (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')
            WHERE p.target_country=''
            GROUP BY p.language_code,g.evaluation_daily_limit ORDER BY p.language_code"""
        ).fetchall()
        fed = conn.execute(
            """SELECT DISTINCT ON (language_code) id,language_code,status,machine_passed,
                human_review_required,publish_ready,created_at,content_version_id
            FROM article_quality_evaluations WHERE topic_key LIKE 'phase39t:%%'
              AND topic ILIKE 'Federal Reserve%%'
            ORDER BY language_code,created_at DESC,id DESC"""
        ).fetchall()
        historical_sec = conn.execute(
            """SELECT language_code,status,count(*)::int AS count,max(created_at) AS latest_at
            FROM article_quality_evaluations WHERE topic ILIKE 'Apple Inc. 10-Q%%'
            GROUP BY language_code,status ORDER BY language_code,status"""
        ).fetchall()
        quota_by_language = {row["language_code"]: row for row in quota}
        sec_block = quota_by_language.get("en")
        sec_blocked = bool(sec_block and sec_block["quota_used"] >= sec_block["quota_limit"])
        resource = resource_snapshot()
        eval_audit = conn.execute(
            """INSERT INTO audit_events(event_type,payload) VALUES
            ('evaluation.p4d.sec.quota_assessed',%s) RETURNING id""",
            (Jsonb({
                "phase": "P4-D", "source": "SEC", "new_inference_count": 0,
                "status": "not_run_quota_blocked" if sec_blocked else "not_run",
                "blocking_language": "en" if sec_blocked else None,
                "quota_used": sec_block["quota_used"] if sec_block else None,
                "quota_limit": sec_block["quota_limit"] if sec_block else None,
                "model_started": False, "publish_ready": False,
            }),),
        ).fetchone()

    load_dotenv(ROOT / ".env", override=True)
    settings.cache_clear()
    with connection() as conn:
        identity = conn.execute("SELECT current_database() AS name").fetchone()
        if not identity or identity["name"] != "woori_blog_agent":
            raise SystemExit("Refusing operational snapshot outside project operations DB")
        reviews = conn.execute("SELECT count(*)::int AS count FROM article_human_reviews").fetchone()
        blogs = conn.execute(
            """SELECT b.language_code,b.url,b.blog_id,b.active,b.connection_verified_at,
                b.last_checked_at,b.connection_error,g.status AS oauth_status,g.scopes
            FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
            ORDER BY b.language_code,b.url"""
        ).fetchall()
        verifications = conn.execute(
            """SELECT DISTINCT ON (blog_id) blog_id,payload,created_at
            FROM audit_events WHERE event_type='blogger.verification.completed'
            ORDER BY blog_id,created_at DESC,id DESC"""
        ).fetchall()
        safety = conn.execute(
            """SELECT
                (SELECT count(*)::int FROM blogger_write_operations) AS blogger_write_operations,
                (SELECT count(*)::int FROM publishing_records) AS publishing_records,
                (SELECT count(*)::int FROM article_quality_evaluations WHERE publish_ready) AS publish_ready_evaluations,
                (SELECT count(*)::int FROM publishing_policies WHERE auto_publish_allowed) AS auto_publish_policies,
                (SELECT count(*)::int FROM publishing_jobs WHERE NOT simulation_only OR adapter_type<>'fake') AS non_mock_jobs,
                EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid
                    WHERE c.relname='audit_events' AND p.proname='deny_mutation' AND t.tgenabled='O') AS audit_immutable"""
        ).fetchone()
        mock = conn.execute(
            """SELECT count(*) FILTER (WHERE adapter_type='fake')::int AS attempts,
                count(*) FILTER (WHERE adapter_type<>'fake')::int AS non_mock_attempts,
                count(*) FILTER (WHERE adapter_type='fake' AND outcome='succeeded')::int AS successes
            FROM publication_attempts"""
        ).fetchone()
        blogger_provider = next(
            item for item in external_status()["providers"]
            if item["name"] == "google_blogger_read"
        )
        report = {
            "phase": "4-D", "captured_at": captured.isoformat(),
            "evaluation": {
                "database": evaluation_database_name, "isolated": True,
                "controls": {"paused": controls["paused"], "evaluation_isolated": controls["evaluation_isolated"]},
                "quota": [dict(item) for item in quota],
                "sec": {"actual_inference_count": 0,
                    "status": "not_run_quota_blocked" if sec_blocked else "not_run",
                    "reason": "SEC is behind the required English-first order; English quota is exhausted" if sec_blocked else "no SEC run initiated",
                    "english_quota": dict(sec_block) if sec_block else None,
                    "historical_sec_evaluations_not_this_phase": [dict(row) for row in historical_sec],
                    "audit_event_id": eval_audit["id"]},
                "fed_current_c3": [dict(row) for row in fed],
            },
            "operations": {
                "database": identity["name"], "fed_human_reviews_total": reviews["count"],
                "blogger_mappings": [dict(row) for row in blogs],
                "historical_blogger_read_verifications": [dict(row) for row in verifications],
                "blogger_cost_policy": blogger_provider,
                "blogger_get_requests_sent_this_phase": 0,
                "blogger_get_block_reason": blogger_provider["block_reason"],
                "mock_publication": dict(mock), "safety": dict(safety),
            },
            "resources_before_model": resource,
            "google_official_evidence": {
                "reviewed_on": "2026-10-27",
                "api_fee": "not stated in reviewed Blogger API reference",
                "free_allocation": "not stated in reviewed Blogger API reference",
                "blogger_quota": "not stated in reviewed Blogger API reference",
                "project_billing_attachment": "not inspected; current OAuth scope is Blogger readonly, not Cloud Billing",
                "quota_overage": "application stops on recognized 429/quota response; no paid fallback exists; Google docs say quotas are usage caps, not spending caps",
                "sources": [
                    "https://developers.google.com/blogger/docs/3.0/using",
                    "https://developers.google.com/identity/protocols/oauth2/web-server",
                    "https://docs.cloud.google.com/apis/docs/capping-api-usage",
                    "https://cloud.google.com/api-keys/pricing",
                ],
            },
            "safety": {
                "blogger_live_gets": 0, "blogger_writes": 0,
                "paid_api_calls": 0, "human_reviews_added": 0,
                "publish_ready_true": safety["publish_ready_evaluations"],
                "automatic_publish_policies": safety["auto_publish_policies"],
            },
        }
        ops_event = conn.execute(
            """INSERT INTO audit_events(event_type,payload) VALUES
            ('operations.p4d.readiness_assessed',%s) RETURNING id""",
            (Jsonb({
                "phase": "P4-D", "captured_at": captured.isoformat(),
                "blogger_cost_status": blogger_provider["block_reason"],
                "blogger_gets_sent": 0, "human_reviews_added": 0,
                "publish_ready": False, "real_writes_enabled": False,
                "paid_service_allowance_change": False,
            }),),
        ).fetchone()
        report["operations"]["assessment_audit_event_id"] = ops_event["id"]

    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(output.relative_to(ROOT)), "sec_status": report["evaluation"]["sec"]["status"],
        "fed_human_reviews": reviews["count"], "blogger_cost_status": blogger_provider["block_reason"],
        "blogger_gets": 0, "publish_ready": False}, ensure_ascii=True))


def resource_snapshot() -> dict[str, object]:
    memory = psutil.virtual_memory()
    return {
        "cpu_percent_sample": psutil.cpu_percent(interval=0.5),
        "memory_percent": memory.percent,
        "available_ram_bytes": memory.available,
        "disk_free_bytes": psutil.disk_usage(str(ROOT)).free,
        "model_started": False,
    }


if __name__ == "__main__":
    main()
