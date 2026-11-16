from __future__ import annotations

import json

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
