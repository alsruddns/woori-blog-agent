"""Read-only, secret-safe local service readiness for Windows lifecycle scripts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-ready", action="store_true")
    parser.add_argument("--worker", choices=("research_worker",))
    args = parser.parse_args()
    if not args.database_ready and not args.worker:
        parser.error("select --database-ready or --worker")
    if not load_dotenv(ROOT / ".env", override=True):
        print(json.dumps({"ready": False, "reason": "project_environment_missing"}))
        return 2

    from woori.db import connection

    try:
        with connection() as conn:
            database = conn.execute("SELECT current_database() AS name").fetchone()["name"]
            if database != "woori_blog_agent":
                print(json.dumps({"ready": False, "reason": "unexpected_database"}))
                return 3
            if args.database_ready:
                print(json.dumps({"ready": True, "database": database}))
                return 0
            row = conn.execute(
                """SELECT process_id,status,last_seen_at,last_error_category
                   FROM worker_heartbeats WHERE service_name='research_worker'"""
            ).fetchone()
        if not row:
            print(json.dumps({"ready": False, "service": args.worker, "state": "not_started"}))
            return 4
        last_seen = row["last_seen_at"]
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        age = max(0.0, (datetime.now(UTC) - last_seen.astimezone(UTC)).total_seconds())
        fresh = row["status"] == "running" and age <= 45
        print(json.dumps({
            "ready": fresh,
            "service": args.worker,
            "process_id": row["process_id"],
            "state": row["status"],
            "last_seen_at": last_seen.isoformat(),
            "age_seconds": round(age, 1),
            "last_error_category": row["last_error_category"],
        }, default=str))
        return 0 if fresh else 5
    except (psycopg.Error, OSError, RuntimeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        category = type(exc).__name__.lower()
        print(json.dumps({"ready": False, "reason": category}))
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
