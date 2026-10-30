"""Run one fake job, confirmed private draft, or separately approved live job."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.db import connection
from woori.publication_worker import run_forever, run_once
from woori.publications import publication_worker_status
from woori.worker import _evaluation_database_isolated


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one publication queue job")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true", help="Read-only queue and heartbeat diagnostics")
    mode.add_argument("--evaluation", action="store_true")
    mode.add_argument("--operations-mock-only", action="store_true")
    mode.add_argument("--operations-confirmed-private-drafts", action="store_true")
    mode.add_argument("--operations-approved-live-publications", action="store_true")
    mode.add_argument("--operations-scheduled-auto", action="store_true",
                      help="Process only scheduled-export jobs after the separate scoped DB approval")
    mode.add_argument("--operations-manual-confirmed", action="store_true",
                      help="Process only manual jobs bound to an exact user confirmation event")
    mode.add_argument("--operations-scheduled-auto-and-manual", action="store_true",
                      help="Process scoped scheduled jobs and separately user-confirmed manual jobs")
    mode.add_argument("--operations-scheduled-auto-and-manual-and-trends", action="store_true",
                      help="Process scoped scheduled, exact-confirmed manual, and separately Trends-policy jobs")
    parser.add_argument("--backoff-seconds", type=int, default=30)
    parser.add_argument("--continuous", action="store_true", help="Poll continuously with a DB singleton lock")
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    if not 0 <= args.backoff_seconds <= 3600:
        raise SystemExit("Backoff must be between 0 and 3600 seconds")
    if not 1 <= args.poll_seconds <= 3600:
        raise SystemExit("Poll interval must be between 1 and 3600 seconds")
    if args.continuous and (args.status or args.evaluation):
        raise SystemExit("Continuous mode is supported only for an operations queue mode")
    if args.evaluation:
        load_dotenv(ROOT / ".env", override=False)
        operations_url = dotenv_values(ROOT / ".env").get("DATABASE_URL", "")
        if not operations_url:
            raise SystemExit(
                "Project operations DB reference is required for isolation verification"
            )
        os.environ["WOORI_OPERATION_DATABASE_URL"] = operations_url
        if not load_dotenv(ROOT / ".env.evaluation", override=True):
            raise SystemExit("Evaluation DB configuration is required")
        _evaluation_database_isolated()
    else:
        if not load_dotenv(ROOT / ".env", override=True):
            raise SystemExit("Project operations DB configuration is required")
        with connection() as conn:
            if (
                conn.execute("SELECT current_database() AS name").fetchone()["name"]
                != "woori_blog_agent"
            ):
                raise SystemExit(
                    "Refusing any database other than the dedicated project operations DB"
                )
    if args.status:
        print(json.dumps(publication_worker_status(), ensure_ascii=True, default=str))
        return
    if args.continuous:
        combined = args.operations_scheduled_auto_and_manual or args.operations_scheduled_auto_and_manual_and_trends
        allow_scheduled = args.operations_scheduled_auto or combined
        allow_manual = args.operations_manual_confirmed or combined
        run_forever(
            args.poll_seconds,
            args.backoff_seconds,
            allow_private_drafts=args.operations_confirmed_private_drafts,
            allow_live_publications=args.operations_approved_live_publications,
            allow_scheduled_auto_publications=allow_scheduled,
            allow_manual_confirmed_publications=allow_manual,
            allow_trends_auto_publications=args.operations_scheduled_auto_and_manual_and_trends,
        )
        return
    print(json.dumps(
        run_once(
            args.backoff_seconds,
            allow_private_drafts=args.operations_confirmed_private_drafts,
            allow_live_publications=args.operations_approved_live_publications,
            allow_scheduled_auto_publications=(args.operations_scheduled_auto or args.operations_scheduled_auto_and_manual or args.operations_scheduled_auto_and_manual_and_trends),
            allow_manual_confirmed_publications=(args.operations_manual_confirmed or args.operations_scheduled_auto_and_manual or args.operations_scheduled_auto_and_manual_and_trends),
            allow_trends_auto_publications=args.operations_scheduled_auto_and_manual_and_trends,
        ),
        ensure_ascii=True,
        default=str,
    ))


if __name__ == "__main__":
    main()
