"""Print safe connection metadata; never display ignored environment-file values."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

from woori.secret_scan import database_url_metadata


def main() -> int:
    path = ROOT / ".env.evaluation-migration"
    values = dotenv_values(path)
    url = values.get("MIGRATION_DATABASE_URL")
    if not url:
        print(json.dumps({"status": "not_configured"}))
        return 1
    summary = database_url_metadata(url)
    print(json.dumps({"status": "configured", **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
