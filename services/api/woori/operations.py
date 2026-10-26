import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def health() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    usage = shutil.disk_usage(root)
    free = round(usage.free / usage.total * 100, 1)
    try:
        report = json.loads((root / "backups/health.json").read_text(encoding="utf-8"))
        age = (
            datetime.now(UTC) - datetime.fromisoformat(report["checked_at"])
        ).total_seconds() / 3600
        backup_ok = report["backup_ok"] is True
    except (OSError, ValueError, KeyError, TypeError):
        age = None
        backup_ok = False
    stale = age is None or age > 26
    return {
        "free_disk_percent": free,
        "backup_ok": backup_ok,
        "backup_age_hours": round(age, 1) if age is not None else None,
        "backup_stale": stale,
        "warning": free < 20 or stale or not backup_ok,
    }
