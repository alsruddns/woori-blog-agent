"""Daily backup and local health status; no automatic retention deletion."""

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from woori.db import connection

root = Path(__file__).resolve().parents[1]
result = subprocess.run(
    [sys.executable, str(root / "scripts/backup.py")], cwd=root, capture_output=True, check=False
)
free = shutil.disk_usage(root)
free_percent = round(free.free / free.total * 100, 1)
report = {
    "checked_at": datetime.now(UTC).isoformat(),
    "backup_ok": result.returncode == 0,
    "free_disk_percent": free_percent,
    "warning": result.returncode != 0 or free_percent < 20,
}
(root / "backups").mkdir(exist_ok=True)
(root / "backups/health.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
try:
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
            (
                "operations.backup.warning" if report["warning"] else "operations.backup.completed",
                Jsonb(report),
            ),
        )
except psycopg.Error:
    print("Health report saved locally; audit database unavailable.")
    raise SystemExit(1) from None
print(json.dumps(report))
if result.returncode != 0:
    raise SystemExit(1)
