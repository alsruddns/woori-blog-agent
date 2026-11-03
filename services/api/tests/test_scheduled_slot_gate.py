from __future__ import annotations

from datetime import datetime
from pathlib import Path

from woori.scheduled_slot_gate import wait_for_scheduled_slot

SLOT = "2026-11-03T09:00:00+09:00"
INVOCATION = {
    "execution_mode": "scheduled",
    "automation_id": "automation-7",
    "scheduled_slot": SLOT,
    "occurrence_id": "codex-slot:automation-7:20261103T0900KST",
    "occurrence_id_source": "project_derived_kst_slot",
    "scheduler_occurrence_id": None,
}


def test_0856_invocation_waits_once_without_changing_configured_occurrence(tmp_path: Path) -> None:
    instant = [datetime.fromisoformat("2026-11-03T08:56:06+09:00")]
    sleeps: list[float] = []
    states: list[tuple[str, str | None]] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        instant[0] = datetime.fromisoformat(SLOT)

    result = wait_for_scheduled_slot(
        INVOCATION, tmp_path, now=lambda: instant[0], sleep=sleep,
        record=lambda _root, _invocation, status, reason: states.append((status, reason)) or {},
    )

    assert result == {"state": "ready", "wait_seconds": 234, "scheduled_slot": SLOT}
    assert sleeps == [234]
    assert [status for status, _ in states] == ["waiting_for_slot", "scheduled"]
    assert INVOCATION["occurrence_id"] == "codex-slot:automation-7:20261103T0900KST"


def test_slot_time_runs_without_sleep(tmp_path: Path) -> None:
    states: list[str] = []
    result = wait_for_scheduled_slot(
        INVOCATION, tmp_path,
        now=lambda: datetime.fromisoformat(SLOT),
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected wait")),
        record=lambda _root, _invocation, status, _reason: states.append(status) or {},
    )
    assert result["state"] == "ready"
    assert result["wait_seconds"] == 0
    assert states == ["scheduled"]


def test_four_minutes_late_remains_in_existing_five_minute_window(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        INVOCATION, tmp_path,
        now=lambda: datetime.fromisoformat("2026-11-03T09:04:00+09:00"),
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected wait")),
        record=lambda *_args: {},
    )
    assert result["state"] == "ready"
    assert result["scheduled_slot"] == SLOT


def test_more_than_five_minutes_late_is_deferred(tmp_path: Path) -> None:
    states: list[str] = []
    result = wait_for_scheduled_slot(
        INVOCATION, tmp_path,
        now=lambda: datetime.fromisoformat("2026-11-03T09:05:01+09:00"),
        record=lambda _root, _invocation, status, _reason: states.append(status) or {},
    )
    assert result["state"] == "deferred"
    assert result["reason"] == "scheduled_invocation_outside_late_window"
    assert states == ["deferred"]


def test_early_wait_is_single_bounded_sleep_and_deferred_if_interrupted(tmp_path: Path) -> None:
    states: list[str] = []

    def interrupt(_seconds: float) -> None:
        raise InterruptedError

    result = wait_for_scheduled_slot(
        INVOCATION, tmp_path,
        now=lambda: datetime.fromisoformat("2026-11-03T08:56:00+09:00"),
        sleep=interrupt,
        record=lambda _root, _invocation, status, _reason: states.append(status) or {},
    )
    assert result["state"] == "deferred"
    assert result["reason"] == "slot_wait_interrupted"
    assert states == ["waiting_for_slot", "deferred"]


def test_manual_invocation_does_not_wait(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        {"execution_mode": "manual"}, tmp_path,
        now=lambda: datetime.fromisoformat("2026-11-03T08:56:00+09:00"),
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected wait")),
    )
    assert result == {"state": "ready", "wait_seconds": 0, "scheduled_slot": None}
