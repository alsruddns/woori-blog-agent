from __future__ import annotations

from pathlib import Path

from woori.scheduled_slot_gate import wait_for_scheduled_slot

SLOT = "2026-11-03T09:00:00+09:00"
AUTOMATION_ID = "automation-7"
SESSION_ID = "01a1a935-87a4-7603-98ba-c603e2ecd08f"


def invocation(executed_at: str = "2026-11-03T08:55:43+09:00") -> dict[str, object]:
    return {
        "execution_mode": "scheduled",
        "trigger": "automation_cron_scheduled",
        "evidence_source": "codex_desktop_local_session_record",
        "provenance_self_reported": True,
        "automation_id": AUTOMATION_ID,
        "session_id": SESSION_ID,
        "executed_at": executed_at,
        "scheduled_slot": SLOT,
        "occurrence_id": "codex-slot:automation-7:20261103T0900KST",
        "occurrence_id_source": "project_derived_kst_slot",
        "scheduler_occurrence_id": None,
    }


def test_verified_scheduled_invocation_257_seconds_early_resolves_without_sleep(
    tmp_path: Path,
) -> None:
    states: list[tuple[str, str | None]] = []

    def record(_root: Path, _invocation: dict[str, object], status: str, reason: str | None) -> dict[str, str]:
        states.append((status, reason))
        return {"status": status}

    result = wait_for_scheduled_slot(
        invocation(),
        tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("must not wait for slot")),
        record=record,
    )

    assert result == {
        "state": "ready",
        "reason": "verified_scheduled_trigger_before_slot",
        "wait_seconds": 0,
        "scheduled_slot": SLOT,
    }
    assert states == [("scheduled", "verified_scheduled_trigger_before_slot")]


def test_exactly_five_minutes_before_is_accepted_without_sleep(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        invocation("2026-11-03T08:55:00+09:00"),
        tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("must not wait for slot")),
        record=lambda *_args: {},
    )
    assert result["state"] == "ready"
    assert result["wait_seconds"] == 0


def test_one_second_before_slot_is_ready(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        invocation("2026-11-03T08:59:59+09:00"),
        tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("must not wait for slot")),
        record=lambda *_args: {},
    )
    assert result["state"] == "ready"
    assert result["reason"] == "verified_scheduled_trigger_before_slot"


def test_at_slot_and_after_slot_run_without_sleep(tmp_path: Path) -> None:
    at_slot = wait_for_scheduled_slot(
        invocation(SLOT), tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected wait")),
        record=lambda *_args: {},
    )
    after_slot = wait_for_scheduled_slot(
        invocation("2026-11-03T09:04:00+09:00"), tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected wait")),
        record=lambda *_args: {},
    )
    assert at_slot["state"] == after_slot["state"] == "ready"
    assert at_slot["wait_seconds"] == after_slot["wait_seconds"] == 0


def test_beyond_five_minute_early_window_expires(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        invocation("2026-11-03T08:54:59+09:00"),
        tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("must not wait indefinitely")),
        record=lambda *_args: {},
    )
    assert result["state"] == "expired"
    assert result["reason"] == "scheduled_slot_too_far_in_future"


def test_beyond_five_minute_late_window_expires(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        invocation("2026-11-03T09:06:00+09:00"),
        tmp_path,
        record=lambda *_args: {},
    )
    assert result["state"] == "expired"
    assert result["reason"] == "scheduled_invocation_outside_late_window"


def test_scheduled_mode_without_verified_trigger_is_rejected(tmp_path: Path) -> None:
    unverified = invocation()
    unverified.pop("trigger")
    result = wait_for_scheduled_slot(
        unverified,
        tmp_path,
        record=lambda *_args: {},
    )
    assert result["state"] == "rejected"
    assert result["reason"] == "scheduled_trigger_identity_unverified"


def test_wrong_trigger_and_wrong_occurrence_are_rejected(tmp_path: Path) -> None:
    wrong_trigger = invocation()
    wrong_trigger["trigger"] = "automation_cron_run_now"
    wrong_occurrence = invocation()
    wrong_occurrence["occurrence_id"] = "codex-slot:automation-8:20261103T0900KST"
    for candidate in (wrong_trigger, wrong_occurrence):
        result = wait_for_scheduled_slot(
            candidate,
            tmp_path,
            record=lambda *_args: {},
        )
        assert result["state"] == "rejected"


def test_manual_invocation_does_not_wait_or_gain_scheduled_provenance(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        {"execution_mode": "manual"},
        tmp_path,
        sleep=lambda _: (_ for _ in ()).throw(AssertionError("unexpected wait")),
    )
    assert result == {"state": "ready", "wait_seconds": 0, "scheduled_slot": None}


def test_progress_failure_does_not_resolve_invocation(tmp_path: Path) -> None:
    result = wait_for_scheduled_slot(
        invocation(),
        tmp_path,
        record=lambda *_args: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    assert result["state"] == "deferred"
    assert result["reason"] == "slot_ready_progress_unavailable"


def test_turn_minute_controls_slot_window_without_client_wall_clock(tmp_path: Path) -> None:
    candidate = invocation("2026-11-03T12:05:02+09:00")
    candidate["scheduled_slot"] = "2026-11-03T12:00:00+09:00"
    candidate["occurrence_id"] = "codex-slot:automation-7:20261103T1200KST"
    result = wait_for_scheduled_slot(
        candidate,
        tmp_path,
        record=lambda *_args: {},
    )
    assert result["state"] == "ready"
    assert result["reason"] == "scheduled_slot_due_or_within_late_window"
