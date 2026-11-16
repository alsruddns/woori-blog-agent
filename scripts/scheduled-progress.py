"""Record actual Local Automation invocation progress without service credentials."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

if __name__ == "__main__":
    from woori.automation_invocation import resolve_current_invocation
    from woori.scheduled_pending import record_progress

    parser = argparse.ArgumentParser()
    parser.add_argument("--automation-id", required=True)
    parser.add_argument(
        "--status",
        required=True,
        choices=(
            "scheduled",
            "waiting_for_slot",
            "duplicate_check_running",
            "duplicate_check_completed",
            "researching",
            "writing",
            "manuscript_created",
            "import_running",
            "import_completed",
            "publication_queued",
            "publication_completed",
            "usage_limit_waiting",
            "policy_waiting",
            "deferred",
            "failed",
        ),
    )
    args = parser.parse_args()
    try:
        invocation = resolve_current_invocation(args.automation_id, project_root=ROOT)
        result = record_progress(ROOT / ".local/gpt-scheduled-import", invocation, args.status)
    except (OSError, ValueError, TypeError):
        print(
            json.dumps(
                {"recorded": False, "reason": "verified_invocation_or_local_store_unavailable"}
            )
        )
        raise SystemExit(2) from None
    print(json.dumps({"recorded": True, **result}, ensure_ascii=True))
