from __future__ import annotations

import json

from scripts import scheduled_duplicate_check as duplicate_cli


def test_generation_preflight_records_running_then_terminal_result(monkeypatch, capsys) -> None:
    from woori import automation_invocation, scheduled_pending, scheduled_slot_gate

    invocation = {
        "execution_mode": "scheduled",
        "automation_id": "automation-7",
        "session_id": "01234567-89ab-cdef-0123-456789abcdef",
        "scheduled_slot": "2026-11-03T09:00:00+09:00",
        "occurrence_id": "codex-slot:automation-7:20261103T0900KST",
    }
    transitions: list[tuple[str, str | None, str | None]] = []
    monkeypatch.setattr(automation_invocation, "current_automation_id", lambda **_kw: "automation-7")
    monkeypatch.setattr(
        automation_invocation, "resolve_current_invocation", lambda *_args, **_kw: invocation
    )
    monkeypatch.setattr(
        scheduled_slot_gate,
        "wait_for_scheduled_slot",
        lambda _invocation, _root: {"state": "ready", "wait_seconds": 0},
    )
    monkeypatch.setattr(
        scheduled_pending,
        "record_progress",
        lambda _root, current, status, reason=None: transitions.append(
            (status, current["occurrence_id"], reason)
        ) or {},
    )
    monkeypatch.setattr(
        duplicate_cli,
        "check_duplicate",
        lambda _payload: {
            "status": "unknown",
            "local_status": "not_found",
            "remote_status": "not_checked",
            "draft_import_allowed": True,
        },
    )

    result = duplicate_cli.main([
        "--stage", "generation",
        "--language-code", "en",
        "--target-country", "US",
        "--target-blog-id", "registered-blog",
        "--event-group-id", "stable-event-20261103",
        "--topic", "A current event with verified sources",
    ])

    assert result == 0
    assert [row[0] for row in transitions] == [
        "duplicate_check_running", "duplicate_check_completed"
    ]
    assert all(row[1] == invocation["occurrence_id"] for row in transitions)
    printed = json.loads(capsys.readouterr().out)
    assert printed["remote_status"] == "not_checked"
    assert printed["draft_import_allowed"] is True


def test_generation_preflight_records_completion_even_when_check_errors(monkeypatch, capsys) -> None:
    from woori import automation_invocation, scheduled_pending, scheduled_slot_gate

    invocation = {
        "execution_mode": "scheduled",
        "automation_id": "automation-7",
        "session_id": "01234567-89ab-cdef-0123-456789abcdef",
        "scheduled_slot": "2026-11-03T09:00:00+09:00",
        "occurrence_id": "codex-slot:automation-7:20261103T0900KST",
    }
    transitions: list[str] = []
    monkeypatch.setattr(automation_invocation, "current_automation_id", lambda **_kw: "automation-7")
    monkeypatch.setattr(
        automation_invocation, "resolve_current_invocation", lambda *_args, **_kw: invocation
    )
    monkeypatch.setattr(
        scheduled_slot_gate,
        "wait_for_scheduled_slot",
        lambda _invocation, _root: {"state": "ready", "wait_seconds": 0},
    )
    monkeypatch.setattr(
        scheduled_pending, "record_progress",
        lambda _root, _current, status, _reason=None: transitions.append(status) or {},
    )

    def failed(_payload):
        raise RuntimeError("must be sanitized")

    monkeypatch.setattr(duplicate_cli, "check_duplicate", failed)
    result = duplicate_cli.main([
        "--stage", "generation",
        "--language-code", "en",
        "--target-country", "US",
        "--target-blog-id", "registered-blog",
        "--event-group-id", "stable-event-20261103",
        "--topic", "A current event with verified sources",
    ])

    assert result == 3
    assert transitions == ["duplicate_check_running", "duplicate_check_completed"]
    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == "duplicate_preflight_internal_error"
    assert "must be sanitized" not in capsys.readouterr().err
