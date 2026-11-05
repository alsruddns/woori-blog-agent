"""Resolve the current Codex Desktop Automation trigger without guessing."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.automation_invocation import resolve_current_invocation


def _diagnostic(event: str, started: float, **details: object) -> None:
    """Flush safe progress to stderr so a long slot wait is not mistaken for a hang."""
    payload = {
        "event": event,
        "pid": os.getpid(),
        "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
        **details,
    }
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True), file=sys.stderr, flush=True)


def _safe_reason(exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return type(exc).__name__


def _resolver_state(reason: str) -> str:
    if "ambiguous" in reason or reason.endswith("_missing_or_ambiguous"):
        return "AMBIGUOUS"
    if "not_active" in reason or "outside_" in reason:
        return "EXPIRED"
    if "mismatch" in reason or "unrecognized" in reason or "not_codex_desktop" in reason:
        return "REJECTED"
    return "FAILED"


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(
        description="Classify the current Codex Desktop Local Automation run from its exact local session trigger"
    )
    parser.add_argument("--automation-id", required=True)
    args = parser.parse_args(argv)
    _diagnostic(
        "resolver_started",
        started,
        automation_id=args.automation_id,
        cwd=str(Path.cwd()),
        command=[
            sys.executable,
            str(Path(__file__).resolve()),
            "--automation-id",
            args.automation_id,
        ],
    )
    try:
        _diagnostic("invocation_resolution_started", started)
        result = resolve_current_invocation(args.automation_id, project_root=ROOT)
        _diagnostic(
            "invocation_resolved",
            started,
            execution_mode=result.get("execution_mode"),
            session_id=result.get("session_id"),
            scheduled_slot=result.get("scheduled_slot"),
        )
        if result["execution_mode"] == "scheduled":
            from woori.scheduled_slot_gate import wait_for_scheduled_slot

            slot_text = result.get("scheduled_slot")
            seconds_until_slot = None
            executed_at_text = result.get("executed_at")
            if isinstance(slot_text, str) and isinstance(executed_at_text, str):
                slot = datetime.fromisoformat(slot_text)
                executed_at = datetime.fromisoformat(executed_at_text)
                seconds_until_slot = round(
                    (slot.astimezone(UTC) - executed_at.replace(second=0, microsecond=0).astimezone(UTC)).total_seconds()
                )
            _diagnostic(
                "scheduled_slot_gate_started",
                started,
                scheduled_slot=slot_text,
                seconds_until_slot=seconds_until_slot,
                gate_policy="verified_trigger_continues_without_sleep_inside_bounded_window",
            )
            slot_gate = wait_for_scheduled_slot(
                result, ROOT / ".local/gpt-scheduled-import"
            )
            _diagnostic(
                "scheduled_slot_gate_finished",
                started,
                state=slot_gate.get("state"),
                reason=slot_gate.get("reason"),
                wait_seconds=slot_gate.get("wait_seconds"),
            )
            result["slot_gate"] = slot_gate
            if slot_gate["state"] != "ready":
                state = {
                    "rejected": "REJECTED",
                    "expired": "EXPIRED",
                    "waiting_for_slot": "WAITING_FOR_SLOT",
                    "deferred": "FAILED",
                }.get(str(slot_gate["state"]), "FAILED")
                print(
                    json.dumps(
                        {
                            "resolved": False,
                            "status": "deferred",
                            "resolver_state": state,
                            "reason": slot_gate["reason"],
                            "invocation": result,
                            "diagnostics": {
                                "pid": os.getpid(),
                                "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
                            },
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
                            "resolver_state": "REJECTED",
                            "reason": policy.get("reason", "automatic_authoring_disabled"),
                            "invocation": result,
                            "policy": policy,
                            "diagnostics": {
                                "pid": os.getpid(),
                                "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
                            },
                        },
                        ensure_ascii=True,
                    )
                )
                return 3
            from woori.scheduled_execution_receipts import record

            record(result)
            result["automation_policy"] = policy
    except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        reason = _safe_reason(exc)
        state = _resolver_state(reason)
        _diagnostic("resolver_failed", started, reason=reason, resolver_state=state)
        print(
            json.dumps(
                {
                    "resolved": False,
                    "status": "blocked",
                    "resolver_state": state,
                    "reason": reason,
                    "diagnostics": {
                        "pid": os.getpid(),
                        "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
                    },
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    diagnostics = {
        "pid": os.getpid(),
        "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
    }
    _diagnostic("resolver_completed", started, execution_mode=result.get("execution_mode"))
    print(json.dumps({"resolved": True, "resolver_state": "RESOLVED", **result, "diagnostics": diagnostics}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
