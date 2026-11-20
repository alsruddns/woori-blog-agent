from __future__ import annotations

import json
from datetime import datetime

import pytest
from woori import scheduled_execution_receipts as receipts


def _invocation(session_id: str) -> dict[str, object]:
    return {
        "execution_mode": "scheduled",
        "automation_id": "automation-15",
        "session_id": session_id,
        "scheduled_slot": "2026-11-03T20:00:00+09:00",
        "occurrence_id": "codex-slot:automation-15:20261103T2000KST",
        "occurrence_id_source": "project_derived_kst_slot",
        "scheduler_occurrence_id": None,
        "executed_at": "2026-11-03T19:58:20+09:00",
    }


def test_occurrence_receipt_is_exclusive_and_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(receipts, "ROOT", tmp_path)
    first = _invocation("01a1a10f-5945-70a3-b4ee-793ec544c10e")
    competing = _invocation("01a1a10f-5945-70a3-b4ee-793ec544c10f")

    receipts.record(first)
    receipts.record(first)

    receipt = receipts._path(str(first["occurrence_id"]), create=False)
    before = receipt.read_bytes()
    with pytest.raises(ValueError, match="execution_receipt_identity_conflict"):
        receipts.record(competing)

    assert receipt.read_bytes() == before
    stored = json.loads(before)
    assert stored["session_id"] == first["session_id"]
    assert stored["occurrence_id"] == first["occurrence_id"]


def test_receipt_rechecks_completed_scheduled_turn_and_rejects_manual(tmp_path, monkeypatch):
    from woori import automation_invocation

    monkeypatch.setattr(receipts, "ROOT", tmp_path)
    monkeypatch.setattr(automation_invocation, "_codex_home", lambda _env: tmp_path)
    monkeypatch.setattr(automation_invocation, "_automation_config", lambda *_args: {})
    monkeypatch.setattr(automation_invocation, "_configured_slot_near",
                        lambda *_args: datetime.fromisoformat("2026-11-03T20:00:00+09:00"))
    inv = _invocation("01a1a10f-5945-70a3-b4ee-793ec544c10e")
    turn = "01a1a10f-5945-70a3-b4ee-793ec544c111"
    folder = tmp_path / "sessions"
    folder.mkdir()
    path = folder / f"rollout-{inv['session_id']}.jsonl"
    records = [
        {"type": "session_meta", "payload": {"session_id": inv["session_id"], "originator": "Codex Desktop", "thread_source": "automation", "cwd": str(tmp_path)}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn, "started_at": datetime.fromisoformat(str(inv["executed_at"])).timestamp(), "turn_attribution": {"turn_id": turn, "turn_trigger": "automation_cron_scheduled"}}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "Automation ID: automation-15"}]}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in records) + "\n", encoding="utf-8")
    receipts.record(inv)
    assert receipts.verify(inv)
    records[1]["payload"]["turn_attribution"]["turn_trigger"] = "automation_cron_run_now"
    path.write_text("\n".join(json.dumps(x) for x in records) + "\n", encoding="utf-8")
    assert not receipts.verify(inv)
