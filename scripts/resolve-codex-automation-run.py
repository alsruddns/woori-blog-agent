"""Resolve the current Codex Desktop Automation trigger without guessing."""

from __future__ import annotations

import argparse
import json
import subprocess
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
        if result["execution_mode"] == "scheduled":
            from woori.scheduled_slot_gate import wait_for_scheduled_slot

            slot_gate = wait_for_scheduled_slot(
                result, ROOT / ".local/gpt-scheduled-import"
            )
            result["slot_gate"] = slot_gate
            if slot_gate["state"] != "ready":
                print(
                    json.dumps(
                        {
                            "resolved": False,
                            "status": "deferred",
                            "reason": slot_gate["reason"],
                            "invocation": result,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                )
                return 3
            check = subprocess.run(
                [sys.executable, str(ROOT / "scripts/automation-policy-check.py")],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            policy = json.loads(check.stdout)
            if check.returncode != 0 or policy.get("allowed") is not True:
                from woori.scheduled_pending import record_progress

                record_progress(
                    ROOT / ".local/gpt-scheduled-import",
                    result,
                    "policy_waiting",
                    str(policy.get("reason", "automatic_authoring_disabled"))[:200],
                )
                print(
                    json.dumps(
                        {
                            "resolved": False,
                            "status": "policy_waiting",
                            "reason": policy.get("reason", "automatic_authoring_disabled"),
                            "invocation": result,
                            "policy": policy,
                        },
                        ensure_ascii=True,
                    )
                )
                return 3
            from woori.scheduled_execution_receipts import record

            record(result)
            result["automation_policy"] = policy
    except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"resolved": False, "reason": str(exc)[:200]}, ensure_ascii=True))
        return 2
    print(json.dumps({"resolved": True, **result}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
