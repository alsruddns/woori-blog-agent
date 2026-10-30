"""Resolve the current Codex Desktop Automation trigger without guessing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.automation_invocation import resolve_current_invocation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify the current Codex Desktop Local Automation run from its exact local session trigger"
    )
    parser.add_argument("--automation-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = resolve_current_invocation(args.automation_id, project_root=ROOT)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"resolved": False, "reason": str(exc)[:200]}, ensure_ascii=True))
        return 2
    print(json.dumps({"resolved": True, **result}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
