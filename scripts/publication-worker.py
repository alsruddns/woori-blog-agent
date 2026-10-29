"""Run one fake job or an explicitly confirmed private Blogger draft job."""

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
from woori.publication_worker import run_once
from woori.worker import _evaluation_database_isolated


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one publication queue job")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--evaluation", action="store_true")
    mode.add_argument("--operations-mock-only", action="store_true")
    mode.add_argument("--operations-confirmed-private-drafts", action="store_true")
    parser.add_argument("--backoff-seconds", type=int, default=30)
    args = parser.parse_args()
    if not 0 <= args.backoff_seconds <= 3600:
        raise SystemExit("Backoff must be between 0 and 3600 seconds")
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
    print(json.dumps(
        run_once(
            args.backoff_seconds,
            allow_private_drafts=args.operations_confirmed_private_drafts,
        ),
        ensure_ascii=True,
        default=str,
    ))


if __name__ == "__main__":
    main()
