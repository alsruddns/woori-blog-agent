from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "resolve-codex-automation-run.py"
SPEC = importlib.util.spec_from_file_location("resolve_scheduled_automation_cli", SCRIPT)
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cli
SPEC.loader.exec_module(cli)


def test_resolver_emits_flushed_stage_diagnostics_and_final_elapsed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "resolve_current_invocation",
        lambda *_args, **_kwargs: {
            "execution_mode": "manual",
            "automation_id": "automation-15",
            "session_id": "01a1a10f-5945-70a3-b4ee-793ec544c10e",
        },
    )

    assert cli.main(["--automation-id", "automation-15"]) == 0

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    diagnostics = [json.loads(line) for line in captured.err.splitlines()]
    assert result["resolved"] is True
    assert result["execution_mode"] == "manual"
    assert result["diagnostics"]["pid"] > 0
    assert result["diagnostics"]["elapsed_ms"] >= 0
    assert [item["event"] for item in diagnostics] == [
        "resolver_started",
        "invocation_resolution_started",
        "invocation_resolved",
        "resolver_completed",
    ]
    assert diagnostics[0]["command"][-2:] == ["--automation-id", "automation-15"]


def test_scheduled_wait_is_reported_before_the_bounded_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    invocation = {
        "execution_mode": "scheduled",
        "automation_id": "automation-15",
        "session_id": "01a1a10f-5945-70a3-b4ee-793ec544c10e",
        "scheduled_slot": "2026-11-03T20:00:00+09:00",
    }
    monkeypatch.setattr(cli, "resolve_current_invocation", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(
        "woori.scheduled_slot_gate.wait_for_scheduled_slot",
        lambda *_args, **_kwargs: {
            "state": "ready",
            "wait_seconds": 40,
            "scheduled_slot": invocation["scheduled_slot"],
        },
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, '{"allowed": true}', ""),
    )
    monkeypatch.setattr("woori.scheduled_execution_receipts.record", lambda *_args: None)

    assert cli.main(["--automation-id", "automation-15"]) == 0

    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.err.splitlines()]
    wait_event = next(item for item in events if item["event"] == "scheduled_slot_gate_started")
    assert wait_event["scheduled_slot"] == invocation["scheduled_slot"]
    assert wait_event["expected_wait_seconds"] is not None
    assert any(item["event"] == "scheduled_slot_gate_finished" for item in events)
    result = json.loads(captured.out)
    assert result["resolved"] is True
    assert result["slot_gate"]["state"] == "ready"


def test_unresolved_mode_timeout_is_blocked_without_rewriting_it_as_scheduled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("resolve-current-invocation", 30)

    monkeypatch.setattr(cli, "resolve_current_invocation", timeout)

    assert cli.main(["--automation-id", "automation-15"]) == 2

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    events = [json.loads(line) for line in captured.err.splitlines()]
    assert result["resolved"] is False
    assert result["status"] == "blocked"
    assert result["reason"] == "TimeoutExpired"
    assert "execution_mode" not in result
    assert events[-1]["event"] == "resolver_failed"
    assert events[-1]["reason"] == "TimeoutExpired"
