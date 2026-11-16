"""Build from a fresh source copy without removing existing user/build files."""

import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

root = Path(__file__).resolve().parents[1]
source = root / "build" / ("isolated-wheel-" + uuid4().hex)
source.mkdir(parents=True)
shutil.copy2(root / "pyproject.toml", source / "pyproject.toml")
shutil.copytree(
    root / "services/api/woori",
    source / "services/api/woori",
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
)
result = subprocess.run(
    [sys.executable, "-m", "pip", "wheel", str(source), "--no-deps", "-w", str(root / "dist")],
    check=False,
)
if result.returncode:
    raise SystemExit("Isolated wheel build failed")
wheel = max((root / "dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
with ZipFile(wheel) as archive:
    if any("tests/" in name or ".env" in name for name in archive.namelist()):
        raise SystemExit("Unexpected file packaged")
print("Isolated Python wheel verified: no test harness or secret configuration.")
