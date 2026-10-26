"""Capture Phase 4-C preflight and append an audit record for a quota-blocked SEC run."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psutil
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
load_dotenv(ROOT / ".env.evaluation", override=True)
from woori.config import settings

settings.cache_clear()

from woori import pipeline
from woori.db import connection

run_id = uuid4()
with connection() as conn:
    identity = conn.execute("SELECT current_database() AS name").fetchone()
    controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
    if identity is None or identity["name"] != "woori_blog_agent_eval":
        raise SystemExit("Refusing to record assessment outside the isolated evaluation database")
    if controls is None or not pipeline.evaluation_database_isolated(conn, controls):
        raise SystemExit("Evaluation DB isolation check failed")
    quota = conn.execute(
        """SELECT p.language_code,g.evaluation_daily_limit AS quota_limit,
            count(*) FILTER (WHERE j.evaluation_only)::int AS quota_used
        FROM language_profiles p JOIN languages l ON l.code=p.language_code AND l.active
        JOIN generation_settings g ON g.profile_id=p.id
        LEFT JOIN generation_targets t ON t.profile_id=p.id
        LEFT JOIN generation_jobs j ON j.run_id=t.run_id AND j.created_at >=
            (date_trunc('day',now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul')
        WHERE p.language_code IN ('en','ko','ja','zh-CN') AND p.target_country=''
        GROUP BY p.language_code,g.evaluation_daily_limit ORDER BY p.language_code"""
    ).fetchall()
    english = next((row for row in quota if row["language_code"] == "en"), None)
    if english is None:
        raise SystemExit("English evaluation quota profile is missing")
    sec_status = "blocked_quota_exhausted" if english["quota_used"] >= english["quota_limit"] else "not_run"
    if sec_status == "blocked_quota_exhausted":
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('evaluation.p4c.sec.quota_blocked',%s)",
            (Jsonb({
                "assessment_run_id": str(run_id), "phase": "P4-C", "source": "SEC",
                "language": "en", "quota_used": english["quota_used"],
                "quota_limit": english["quota_limit"], "model_started": False,
                "quota_reset_policy": "KST midnight", "publish_ready": False,
            }),),
        )
    sec_history = conn.execute(
        """SELECT language_code,status,count(*)::int AS count
        FROM article_quality_evaluations WHERE topic ILIKE 'Apple Inc. 10-Q%'
        GROUP BY language_code,status ORDER BY language_code,status"""
    ).fetchall()
    fed = conn.execute(
        """SELECT language_code,count(DISTINCT content_version_id)::int AS versions,
            count(DISTINCT content_version_id) FILTER (WHERE machine_passed)::int AS machine_passed
        FROM article_quality_evaluations
        WHERE topic_key LIKE 'phase39t:%%' AND topic ILIKE 'Federal Reserve%%'
        GROUP BY language_code ORDER BY language_code"""
    ).fetchall()

load_dotenv(ROOT / ".env", override=True)
settings.cache_clear()
from woori.db import connection as ops_connection
from woori.external_policy import status as external_status
from woori.google_http import READ_SCOPE

expected_blogs = {
    "ko": "https://trend-ko.blogspot.com",
    "en": "https://trend-journal-en.blogspot.com",
    "zh-CN": "https://trend-zh.blogspot.com",
    "ja": "https://trend-ja.blogspot.com",
}
with ops_connection() as conn:
    op_identity = conn.execute("SELECT current_database() AS name").fetchone()
    if op_identity is None or op_identity["name"] != "woori_blog_agent":
        raise SystemExit("Refusing to inspect Blogger status outside the project operations DB")
    account_count = conn.execute(
        "SELECT count(*)::int AS n FROM google_connections WHERE status='connected' AND scopes=%s",
        ([READ_SCOPE],),
    ).fetchone()["n"]
    blogs = conn.execute(
        """SELECT b.language_code,b.url,b.blog_id,b.active,b.connection_verified_at,
            b.last_checked_at,b.connection_error,g.status AS oauth_status,g.scopes
        FROM blogger_blogs b LEFT JOIN google_connections g ON g.id=b.oauth_connection_id
        ORDER BY b.language_code,b.url"""
    ).fetchall()
    safety = conn.execute(
        """SELECT (SELECT count(*)::int FROM blogger_write_operations) AS blogger_write_operations,
            (SELECT count(*)::int FROM publishing_records) AS publishing_records,
            (SELECT count(*)::int FROM article_quality_evaluations WHERE publish_ready) AS publish_ready_evaluations,
            (SELECT count(*)::int FROM publishing_policies WHERE auto_publish_allowed) AS auto_publish_policies,
            EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_proc p ON p.oid=t.tgfoid
                WHERE c.relname='audit_events' AND p.proname='deny_mutation' AND t.tgenabled='O') AS audit_immutable"""
    ).fetchone()
    review_count = conn.execute("SELECT count(*)::int AS n FROM article_human_reviews").fetchone()["n"]
    blocked_external = conn.execute(
        """SELECT count(*)::int AS n FROM audit_events
        WHERE event_type='external.call.blocked'
          AND payload->>'provider'='google_blogger_read'
          AND payload->>'reason'='provider_cost_unverified'"""
    ).fetchone()["n"]

provider = next((item for item in external_status()["providers"] if item["name"] == "google_blogger_read"), None)
now = datetime.now(UTC)
report = {
    "phase": "4-C",
    "assessment_run_id": str(run_id),
    "captured_at_utc": now.isoformat(),
    "evaluation_database": {
        "name": "woori_blog_agent_eval", "schema_version": 26,
        "physically_isolated": True, "evaluation_isolated_policy": bool(controls["evaluation_isolated"]),
        "quota_policy": "per-language daily target quota; failures and cancellations count; retries reuse targets; reset at KST midnight",
        "quota": [dict(row) for row in quota],
    },
    "fed_existing_c3": {
        "language_versions": [dict(row) for row in fed],
        "human_review_count_before_phase": review_count,
        "actual_new_inference_in_phase": 0,
        "human_review_required": True,
        "publish_ready": False,
    },
    "sec": {
        "new_actual_inference": sec_status,
        "blocked_reason": "English is first in required order and its evaluation quota is exhausted" if sec_status == "blocked_quota_exhausted" else None,
        "model_started": False,
        "existing_historical_quality_evaluations": [dict(row) for row in sec_history],
        "historical_data_is_not_phase4c_inference": True,
    },
    "blogger_readonly": {
        "connected_accounts_with_readonly_scope": account_count,
        "registered_blogs": [
            {**dict(row), "expected_url_matches": expected_blogs.get(row["language_code"]) == row["url"],
             "readonly_scope": READ_SCOPE in (row["scopes"] or [])}
            for row in blogs
        ],
        "live_api_get_requests_this_phase": 0,
        "live_sync_status": "blocked_before_network_by_zero_cost_provider_gate",
        "provider_policy": provider,
        "blocked_attempts_by_policy": blocked_external,
        "pagination_and_detail_reads": "not_verified_this_phase",
    },
    "safety": {**dict(safety), "paid_api_calls": 0, "external_data_calls_for_ai": 0,
        "operating_posts_changed": 0, "real_blogger_writes_in_this_phase": 0},
    "resources": {"available_ram_bytes": psutil.virtual_memory().available,
        "cpu_percent_sample": psutil.cpu_percent(interval=0.5),
        "disk_free_bytes": psutil.disk_usage(str(ROOT)).free,
        "model_run": False},
}
path = ROOT / "docs" / "development" / "P4-C-evaluation-20261027.json"
if path.exists():
    raise SystemExit("Assessment artifact already exists; refusing to overwrite it")
path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
print(json.dumps({"artifact": str(path.relative_to(ROOT)), "sec_status": sec_status,
    "fed_machine_passed_versions": sum(row["machine_passed"] for row in fed),
    "blogger_live_gets": 0, "blogger_provider_allowed": bool(provider and provider["calls_allowed"]),
    "publish_ready": False}, ensure_ascii=True))
