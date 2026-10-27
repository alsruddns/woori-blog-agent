"""Apply the bounded evaluation quota policy to the isolated evaluation database only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psutil
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
load_dotenv(ROOT / ".env.evaluation", override=True)

from woori.db import connection
from woori.pipeline import evaluation_database_isolated, resources_ok

NEW_LIMIT = 10
EXPECTED_EVALUATION_DATABASE = "woori_blog_agent_eval"
POLICY_EVENT = "evaluation.quota.policy.updated"


def main() -> None:
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.5)
    disk = psutil.disk_usage(str(ROOT))
    with connection() as conn:
        identity = conn.execute(
            "SELECT current_database() AS database_name,current_user AS role_name"
        ).fetchone()
        controls = conn.execute("SELECT * FROM pipeline_controls").fetchone()
        if identity is None or identity["database_name"] != EXPECTED_EVALUATION_DATABASE:
            raise SystemExit("Refusing quota update outside the named evaluation database")
        if controls is None or not evaluation_database_isolated(conn, controls):
            raise SystemExit("Evaluation database isolation could not be confirmed")
        if controls["max_concurrency"] != 1:
            raise SystemExit("Evaluation quota update requires global concurrency to remain one")
        if controls["paused"] or not resources_ok(controls):
            raise SystemExit("Shared pause or CPU/RAM/disk resource gate is closed")
        if conn.execute(
            "SELECT 1 FROM job_runs WHERE status IN ('queued','running') LIMIT 1"
        ).fetchone():
            raise SystemExit("Evaluation queue is not idle; no quota settings were changed")
        profiles = conn.execute(
            """SELECT p.id,p.language_code,g.evaluation_daily_limit
            FROM language_profiles p JOIN languages l ON l.code=p.language_code AND l.active
            JOIN generation_settings g ON g.profile_id=p.id
            WHERE p.target_country='' ORDER BY p.language_code FOR UPDATE OF g"""
        ).fetchall()
        if not profiles:
            raise SystemExit("No active base-language evaluation profiles were found")
        if any(int(row["evaluation_daily_limit"]) not in {2, NEW_LIMIT} for row in profiles):
            raise SystemExit("Unexpected existing quota detected; preserving the current policy")
        previous = [
            {"language_code": row["language_code"], "limit": int(row["evaluation_daily_limit"])}
            for row in profiles
        ]
        already_recorded = conn.execute(
            "SELECT 1 FROM audit_events WHERE event_type=%s LIMIT 1", (POLICY_EVENT,)
        ).fetchone()
        if already_recorded:
            if any(item["limit"] != NEW_LIMIT for item in previous):
                raise SystemExit("Policy audit exists but quotas differ; manual review is required")
            print(json.dumps({"status": "already_applied", "limits": previous}, ensure_ascii=True))
            return
        for row in profiles:
            if int(row["evaluation_daily_limit"]) != NEW_LIMIT:
                conn.execute(
                    "UPDATE generation_settings SET evaluation_daily_limit=%s WHERE profile_id=%s",
                    (NEW_LIMIT, row["id"]),
                )
        after = [{"language_code": row["language_code"], "limit": NEW_LIMIT} for row in profiles]
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (
                POLICY_EVENT,
                Jsonb({
                    "daily_limit_per_active_base_language": NEW_LIMIT,
                    "previous_limits": previous,
                    "new_limits": after,
                    "timezone": "Asia/Seoul",
                    "resets_at": "00:00 Asia/Seoul",
                    "sec_english_priority_reserved_slots": 1,
                    "reserved_within_limit": True,
                    "global_max_concurrency": 1,
                    "resource_gate": {
                        "cpu_limit_percent": int(controls["cpu_percent"]),
                        "ram_limit_percent": int(controls["ram_percent"]),
                        "minimum_available_ram_mib": 6144,
                        "minimum_project_disk_free_gib": 10,
                        "observed_available_ram_mib": round(memory.available / 1024**2),
                        "observed_ram_percent": memory.percent,
                        "observed_cpu_percent": cpu_percent,
                        "observed_project_disk_free_gib": round(disk.free / 1024**3, 2),
                    },
                    "measurement_basis": {
                        "prior_runs": 2,
                        "model": "Qwen3-4B-Q4_K_M.gguf",
                        "elapsed_ms": [26376, 25718],
                        "max_observed_rss_mib": [3380.21, 4880.57],
                        "model_calls_per_run": [5, 5],
                        "interpretation": "Observed per-run cost only; daily aggregate remains capped at ten targets per language and shares global resource gates.",
                    },
                    "quota_usage_reset_or_deleted": False,
                    "operations_quota_changed": False,
                    "paid_fallback": False,
                }),
            ),
        )
        print(json.dumps({
            "status": "applied",
            "database": identity["database_name"],
            "languages": [row["language_code"] for row in profiles],
            "previous_limits": previous,
            "new_limit": NEW_LIMIT,
            "sec_english_reserved_slots": 1,
            "max_concurrency": int(controls["max_concurrency"]),
            "audit_event": POLICY_EVENT,
            "quota_usage_reset_or_deleted": False,
            "operations_quota_changed": False,
            "resource_observation": {
                "cpu_percent": cpu_percent,
                "ram_percent": memory.percent,
                "available_ram_mib": round(memory.available / 1024**2),
                "project_disk_free_gib": round(disk.free / 1024**3, 2),
            },
            "paid_calls": 0,
        }, ensure_ascii=True))


if __name__ == "__main__":
    main()
