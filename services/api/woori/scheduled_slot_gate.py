"""Validate a verified Codex Desktop scheduled invocation against its KST slot.

Codex Desktop can start a scheduled turn shortly before the configured slot.
The exact current trigger and Automation slot are verified before this gate is
called, so a run inside the bounded window can proceed immediately. Waiting in
this CLI would outlive the scheduled model turn and strand the resolver result.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .scheduled_occurrence import validate_occurrence_metadata
from .scheduled_pending import record_progress

MAX_EARLY_SECONDS = 300
MAX_LATE_SECONDS = 300


def _verified_scheduled_identity(invocation: dict[str, Any], slot: datetime) -> bool:
    """Require the identity produced by the current Desktop trigger resolver."""
    if (
        invocation.get("trigger") != "automation_cron_scheduled"
        or invocation.get("evidence_source") != "codex_desktop_local_session_record"
        or invocation.get("provenance_self_reported") is not True
        or invocation.get("occurrence_id_source") not in {
            "scheduler_issued",
            "project_derived_kst_slot",
        }
        or not isinstance(invocation.get("automation_id"), str)
        or not isinstance(invocation.get("occurrence_id"), str)
        or not isinstance(invocation.get("session_id"), str)
        or not isinstance(invocation.get("executed_at"), str)
    ):
        return False
    try:
        UUID(invocation["session_id"])
        validate_occurrence_metadata(
            occurrence_id=invocation["occurrence_id"],
            occurrence_id_source=invocation["occurrence_id_source"],
            scheduler_occurrence_id=invocation.get("scheduler_occurrence_id"),
            automation_id=invocation["automation_id"],
            scheduled_slot=slot,
        )
        executed_at = datetime.fromisoformat(invocation["executed_at"])
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            return False
    except (ValueError, TypeError, KeyError):
        return False
    return True


def wait_for_scheduled_slot(
    invocation: dict[str, Any],
    progress_root: Path,
    *,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
    record: Callable[[Path, dict[str, Any], str, str | None], dict[str, Any]] = record_progress,
) -> dict[str, Any]:
    """Authorize a current scheduled invocation within its bounded slot window.

    This function intentionally never sleeps. A verified Desktop scheduled
    trigger can arrive up to five minutes before its configured slot; blocking
    the local resolver until that slot strands its final result after the
    model turn ends. The trigger, session, occurrence and configured slot are
    mandatory, and the wall clock only rejects an invocation outside the
    already-verified early/late window; it never authorizes a run by itself.
    """
    mode = invocation.get("execution_mode")
    if mode == "manual":
        return {"state": "ready", "wait_seconds": 0, "scheduled_slot": None}
    if mode != "scheduled":
        return {"state": "rejected", "reason": "scheduled_invocation_required",
                "wait_seconds": 0, "scheduled_slot": None}

    slot_text = invocation.get("scheduled_slot")
    if not isinstance(slot_text, str):
        return {"state": "rejected", "reason": "scheduled_slot_missing",
                "wait_seconds": 0, "scheduled_slot": None}
    try:
        slot = datetime.fromisoformat(slot_text)
    except ValueError:
        return {"state": "rejected", "reason": "scheduled_slot_invalid",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    if slot.tzinfo is None or slot.utcoffset() is None:
        return {"state": "rejected", "reason": "scheduled_slot_requires_timezone",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    if not _verified_scheduled_identity(invocation, slot):
        return {"state": "rejected", "reason": "scheduled_trigger_identity_unverified",
                "wait_seconds": 0, "scheduled_slot": slot_text}

    clock = now or (lambda: datetime.now(UTC))
    current = clock()
    if current.tzinfo is None or current.utcoffset() is None:
        return {"state": "rejected", "reason": "system_clock_timezone_missing",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    seconds_until_slot = (slot.astimezone(UTC) - current.astimezone(UTC)).total_seconds()
    if seconds_until_slot > MAX_EARLY_SECONDS:
        return {"state": "expired", "reason": "scheduled_slot_too_far_in_future",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    if seconds_until_slot < -MAX_LATE_SECONDS:
        return {"state": "expired", "reason": "scheduled_invocation_outside_late_window",
                "wait_seconds": 0, "scheduled_slot": slot_text}

    progress_reason = (
        "verified_scheduled_trigger_before_slot"
        if seconds_until_slot > 0
        else "scheduled_slot_due_or_within_late_window"
    )
    try:
        record(progress_root, invocation, "scheduled", progress_reason)
    except (OSError, ValueError, TypeError):
        return {"state": "deferred", "reason": "slot_ready_progress_unavailable",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    return {
        "state": "ready",
        "reason": progress_reason,
        "wait_seconds": 0,
        "scheduled_slot": slot_text,
    }
