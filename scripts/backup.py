"""Custom-format project backup. Credentials are passed only via child environment."""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
url = urlsplit(dotenv_values(root / ".env.migration")["MIGRATION_DATABASE_URL"])
if url.path != "/woori_blog_agent":
    raise SystemExit("Refusing non-project database")
folder = root / "backups"
folder.mkdir(exist_ok=True)
target = folder / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".dump")
env = {**os.environ, "PGPASSWORD": unquote(url.password or "")}
bin_dir = Path("C:/Program Files/PostgreSQL/16/bin")
args = [
    "-h",
    url.hostname or "localhost",
    "-p",
    str(url.port or 5432),
    "-U",
    url.username or "",
    "-d",
    "woori_blog_agent",
]
result = subprocess.run(
    [str(bin_dir / "pg_dump.exe"), *args, "-Fc", "-f", str(target)],
    env=env,
    capture_output=True,
    check=False,
)
if result.returncode:
    raise SystemExit("Backup failed; inspect PostgreSQL availability and backup disk access")
verify = subprocess.run(
    [str(bin_dir / "pg_restore.exe"), "--list", str(target)], capture_output=True, check=False
)
if verify.returncode:
    raise SystemExit("Backup archive validation failed")
print("Backup created and archive catalog verified. Restore rehearsal is a separate procedure.")
