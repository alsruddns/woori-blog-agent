"""Print a truthful scheduler-issued or project-derived occurrence identity."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "api"))

from woori.scheduled_occurrence import occurrence_metadata, verify_configured_slot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Codex Local Automation slot and derive its stable occurrence ID"
    )
    parser.add_argument("--automation-id", required=True)
    parser.add_argument("--scheduled-slot", required=True, help="Configured KST slot, ISO 8601 with +09:00")
    parser.add_argument("--scheduler-occurrence-id", help="Only when the scheduler actually supplied one")
    parser.add_argument(
        "--automations-root", type=Path,
        default=Path.home() / ".codex" / "automations",
    )
    args = parser.parse_args(argv)
    try:
        slot = datetime.fromisoformat(args.scheduled_slot)
        verified = verify_configured_slot(
            automation_id=args.automation_id,
            scheduled_slot=slot,
            automations_root=args.automations_root,
            project_root=PROJECT_ROOT,
        )
        result = occurrence_metadata(
            automation_id=args.automation_id,
            scheduled_slot=slot,
            scheduler_occurrence_id=args.scheduler_occurrence_id,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    result["timezone"] = verified["timezone"]
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
