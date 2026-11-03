"""Bounded KST slot gate for real Codex Local Automation invocations."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .scheduled_pending import record_progress

MAX_EARLY_WAIT_SECONDS = 300
MAX_LATE_SECONDS = 300


def wait_for_scheduled_slot(
    invocation: dict[str, Any],
    progress_root: Path,
    *,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
    record: Callable[[Path, dict[str, Any], str, str | None], dict[str, Any]] = record_progress,
) -> dict[str, Any]:
    """Wait once for a near-future slot, or fail closed with a terminal defer.

    A single bounded sleep avoids busy polling and does not invoke any model,
    research provider, Import API, or Blogger operation.
    """
    if invocation.get("execution_mode") != "scheduled":
        return {"state": "ready", "wait_seconds": 0, "scheduled_slot": None}
    slot_text = invocation.get("scheduled_slot")
    if not isinstance(slot_text, str):
        raise TypeError("scheduled_slot_missing")
    slot = datetime.fromisoformat(slot_text)
    if slot.tzinfo is None or slot.utcoffset() is None:
        raise ValueError("scheduled_slot_requires_timezone")

    clock = now or (lambda: datetime.now(UTC))
    sleeper = sleep or time.sleep

    def current() -> datetime:
        value = clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("system_clock_timezone_missing")
        return value.astimezone(UTC)

    def progress(status: str, reason: str | None) -> bool:
        try:
            record(progress_root, invocation, status, reason)
            return True
        except (OSError, ValueError, TypeError):
            return False

    before = current()
    seconds_until_slot = (slot.astimezone(UTC) - before).total_seconds()
    if seconds_until_slot > MAX_EARLY_WAIT_SECONDS:
        progress("deferred", "scheduled_slot_too_far_in_future")
        return {"state": "deferred", "reason": "scheduled_slot_too_far_in_future",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    if seconds_until_slot > 0:
        wait_seconds = min(MAX_EARLY_WAIT_SECONDS, math.ceil(seconds_until_slot))
        if not progress("waiting_for_slot", "scheduled_slot_not_yet_reached"):
            return {"state": "deferred", "reason": "slot_wait_progress_unavailable",
                    "wait_seconds": 0, "scheduled_slot": slot_text}
        try:
            sleeper(wait_seconds)
        except (InterruptedError, KeyboardInterrupt):
            progress("deferred", "slot_wait_interrupted")
            return {"state": "deferred", "reason": "slot_wait_interrupted",
                    "wait_seconds": wait_seconds, "scheduled_slot": slot_text}
        after = current()
        lateness = (after - slot.astimezone(UTC)).total_seconds()
        if lateness < 0:
            progress("deferred", "clock_or_sleep_did_not_reach_scheduled_slot")
            return {"state": "deferred", "reason": "clock_or_sleep_did_not_reach_scheduled_slot",
                    "wait_seconds": wait_seconds, "scheduled_slot": slot_text}
        if lateness > MAX_LATE_SECONDS:
            progress("deferred", "slot_reached_after_late_window")
            return {"state": "deferred", "reason": "slot_reached_after_late_window",
                    "wait_seconds": wait_seconds, "scheduled_slot": slot_text}
        if not progress("scheduled", "scheduled_slot_reached_after_bounded_wait"):
            return {"state": "deferred", "reason": "slot_ready_progress_unavailable",
                    "wait_seconds": wait_seconds, "scheduled_slot": slot_text}
        return {"state": "ready", "wait_seconds": wait_seconds,
                "scheduled_slot": slot_text}

    lateness = -seconds_until_slot
    if lateness > MAX_LATE_SECONDS:
        progress("deferred", "scheduled_invocation_outside_late_window")
        return {"state": "deferred", "reason": "scheduled_invocation_outside_late_window",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    if not progress("scheduled", "scheduled_slot_due_or_within_late_window"):
        return {"state": "deferred", "reason": "slot_ready_progress_unavailable",
                "wait_seconds": 0, "scheduled_slot": slot_text}
    return {"state": "ready", "wait_seconds": 0, "scheduled_slot": slot_text}
