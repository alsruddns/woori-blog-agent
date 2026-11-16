from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from woori.automation_authoring_contract import select_authoring_contract


def _duplicate_check_module():
    script = Path(__file__).resolve().parents[3] / "scripts" / "scheduled_duplicate_check.py"
    spec = importlib.util.spec_from_file_location("p133_scheduled_duplicate_check", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_now_selects_manual_import_contract_without_scheduled_fields() -> None:
    session_id = str(uuid4())
    run_id = f"codex-manual:automation-15:{uuid4()}"
    origin = {
        "execution_mode": "manual",
        "automation_id": "automation-15",
        "manual_run_id": run_id,
        "session_id": session_id,
        "turn_trigger": "automation_cron_run_now",
        "invoked_at": "2026-11-04T12:00:00+09:00",
    }
    selected = select_authoring_contract({
        "execution_mode": "manual",
        "trigger": "automation_cron_run_now",
        "automation_id": "automation-15",
        "session_id": session_id,
        "manual_run_id": run_id,
        "manual_origin": origin,
    })
    assert selected == {
        "execution_origin": "automation_run_now",
        "envelope_schema": "woori-manual-automation-content-import/1.0",
        "generation_method": "manual_codex_import",
        "origin_field": "manual_origin",
        "run_id": run_id,
    }
    enriched = _duplicate_check_module().attach_execution_contract(
        {"local_status": "not_found", "draft_import_allowed": True, "remote_status": "not_checked"},
        {
            "execution_mode": "manual", "trigger": "automation_cron_run_now",
            "automation_id": "automation-15", "session_id": session_id,
            "manual_run_id": run_id, "manual_origin": origin,
        },
    )
    assert enriched["automation_execution"]["contract"] == selected
    assert enriched["automation_execution"]["invocation"]["manual_run_id"] == run_id


def test_scheduled_run_keeps_scheduled_import_contract() -> None:
    selected = select_authoring_contract({
        "execution_mode": "scheduled",
        "trigger": "automation_cron_scheduled",
        "automation_id": "automation-15",
        "session_id": str(uuid4()),
        "occurrence_id": "codex-slot:automation-15:20261104T1200KST",
        "scheduled_slot": "2026-11-04T12:00:00+09:00",
        "occurrence_id_source": "project_derived_kst_slot",
    })
    assert selected["envelope_schema"] == "woori-scheduled-content-import/1.0"
    assert selected["generation_method"] == "chatgpt_scheduled_export"
    assert selected["origin_field"] == "scheduled_origin"


@pytest.mark.parametrize("invocation", [
    {"execution_mode": "manual", "trigger": "composer", "automation_id": "automation-15", "session_id": str(uuid4())},
    {"execution_mode": "scheduled", "trigger": "automation_cron_run_now", "automation_id": "automation-15", "session_id": str(uuid4())},
])
def test_unverified_or_mixed_invocation_has_no_contract(invocation: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="contract_not_available"):
        select_authoring_contract(invocation)


def test_run_now_identity_mismatch_has_no_contract() -> None:
    session_id = str(uuid4())
    run_id = f"codex-manual:automation-15:{uuid4()}"
    with pytest.raises(ValueError, match="manual_authoring_identity_incomplete"):
        select_authoring_contract({
            "execution_mode": "manual",
            "trigger": "automation_cron_run_now",
            "automation_id": "automation-15",
            "session_id": session_id,
            "manual_run_id": run_id,
            "manual_origin": {
                "execution_mode": "manual",
                "automation_id": "automation-15",
                "manual_run_id": run_id,
                "session_id": str(uuid4()),
                "turn_trigger": "automation_cron_run_now",
            },
        })
