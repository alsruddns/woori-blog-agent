"""Trusted service helper; returns only current automatic-authoring permission."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

if __name__ == "__main__":
    from woori.automation_controls import authoring_permission

    result = authoring_permission()
    print(json.dumps(result))
    raise SystemExit(0 if result["allowed"] else 3)
