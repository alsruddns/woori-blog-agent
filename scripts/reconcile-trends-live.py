"""Reconcile one exact uncertain Trends LIVE job without issuing a write."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.google_http import GoogleFailure
from woori.publication_reconciliation import reconcile_uncertain_trends_live


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    if not load_dotenv(ROOT / ".env", override=True):
        print(json.dumps({"status": "blocked", "reason": "project_environment_missing"}))
        return 2
    try:
        result = reconcile_uncertain_trends_live(args.job_id)
    except GoogleFailure as exc:
        print(json.dumps({"status": "blocked", "reason": exc.category, "blogger_write_performed": False}))
        return 3
    except (OSError, ValueError, RuntimeError, psycopg.Error):
        print(json.dumps({"status": "blocked", "reason": "reconciliation_unavailable", "blogger_write_performed": False}))
        return 4
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
