from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from woori.automation_invocation import resolve_current_invocation
from woori.scheduled_import_inbox import validate_envelope


def _write_automation(root: Path, project: Path) -> Path:
    folder = root / "automation-8"
    folder.mkdir(parents=True)
    (folder / "automation.toml").write_text(
        'id = "automation-8"\nkind = "cron"\nstatus = "ACTIVE"\n'
        'rrule = "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=20;BYMINUTE=0"\n'
        f'cwds = ["{project.as_posix()}"]\n',
        encoding="utf-8",
    )
    return folder


def _session(
    path: Path, *, session_id: str, project: Path, started_at: datetime,
    trigger: str, quota_failure: bool = False,
) -> None:
    records = [
        {"type": "session_meta", "payload": {"session_id": session_id, "id": session_id,
         "originator": "Codex Desktop", "thread_source": "automation", "cwd": str(project)}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "Automation: Test\nAutomation ID: automation-8\nTask code: politics-kr."}]}},
        {"type": "event_msg", "payload": {"type": "task_started", "started_at": started_at.timestamp(),
         "turn_attribution": {"turn_id": str(uuid4()), "turn_trigger": trigger}}},
    ]
    if quota_failure:
        records.append({"type": "event_msg", "payload": {"type": "task_complete",
            "error": {"codex_error_info": "usage_limit_exceeded"}}})
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


def test_explicit_manual_trigger_gets_stable_manual_id_and_known_quota_recovery(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    automations = tmp_path / ".codex" / "automations"
    _write_automation(automations, project)
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    failed_session_id = str(uuid4())
    _session(sessions / f"rollout-{failed_session_id}.jsonl", session_id=failed_session_id,
             project=project, started_at=datetime(2026, 10, 30, 19, 58, 25, tzinfo=UTC).replace(hour=10),
             trigger="automation_cron_scheduled", quota_failure=True)
    manual_session_id = str(uuid4())
    manual_file = sessions / f"rollout-{manual_session_id}.jsonl"
    _session(manual_file, session_id=manual_session_id, project=project,
             started_at=datetime(2026, 10, 30, 14, 17, 22, tzinfo=UTC),
             trigger="automation_cron_run_now")
    env = {"CODEX_THREAD_ID": manual_session_id, "CODEX_HOME": str(tmp_path / ".codex")}
    first = resolve_current_invocation("automation-8", project_root=project, environ=env)
    second = resolve_current_invocation("automation-8", project_root=project, environ=env)
    assert first["execution_mode"] == "manual"
    assert first["manual_run_id"].startswith("codex-manual:automation-8:")
    assert first["manual_run_id"] == second["manual_run_id"]
    origin = first["manual_origin"]
    assert origin["turn_trigger"] == "automation_cron_run_now"
    assert origin["recovery_reason_code"] == "usage_limit_exceeded"
    assert origin["recovery_of_session_id"] == failed_session_id
    assert origin["recovery_of_scheduled_slot"] == "2026-10-30T20:00:00+09:00"
    assert "occurrence_id" not in first


def test_scheduled_trigger_keeps_existing_deterministic_occurrence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    automations = tmp_path / ".codex" / "automations"
    _write_automation(automations, project)
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    _session(sessions / f"rollout-{session_id}.jsonl", session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    result = resolve_current_invocation(
        "automation-8", project_root=project,
        environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(tmp_path / ".codex")},
    )
    assert result["execution_mode"] == "scheduled"
    assert result["scheduled_slot"] == "2026-10-30T20:00:00+09:00"
    assert result["occurrence_id"] == "codex-slot:automation-8:20261030T2000KST"
    assert result["scheduler_occurrence_id"] is None


@pytest.mark.parametrize("trigger", ["automation_cron_retry", "", "automation_cron_scheduled_typo"])
def test_unrecognized_automation_trigger_fails_closed(tmp_path: Path, trigger: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    automations = tmp_path / ".codex" / "automations"
    _write_automation(automations, project)
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    _session(sessions / f"rollout-{session_id}.jsonl", session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC), trigger=trigger)
    with pytest.raises(ValueError, match="current_automation_trigger_unrecognized"):
        resolve_current_invocation(
            "automation-8", project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(tmp_path / ".codex")},
        )


def test_manual_import_envelope_rejects_scheduled_provenance_and_validates_manual_origin() -> None:
    session_id = str(uuid4())
    from woori.content_imports import ManualAutomationImportEnvelope

    payload = {
        "schema_version": "woori-manual-automation-content-import/1.0",
        "submitted_by": "Codex Desktop automation-8 manual run",
        "item": {
            "schema_version": "1.0", "content_id": str(uuid4()), "event_group_id": "politics-kr-20261030",
            "parent_content_id": None, "relation": "original", "source_region": "KR", "language_code": "ko",
            "target_audiences": [{"language_code": "ko", "target_region": "KR",
                "reader_relevance_reason": "The verified Korean policy issue directly affects local readers."}],
            "title": "Evidence based article title for Korean readers",
            "body_markdown": "## Verified update\n\n" + "The official notice explains the documented update and its stated timing. [source:agency]\n\n" * 3,
            "category": "policy", "google_trends_based": False, "source_ids": ["agency"],
            "sources": [{"source_id": "agency", "title": "Official policy notice", "organization": "Public agency",
                "url": "https://example.gov/policy", "observed_at": "2026-10-30T11:00:00+09:00",
                "language_code": "ko", "source_type": "government", "rights_status": "quotation_review_required",
                "rights_note": "A human reviewer must confirm quotation and reuse terms."}],
            "claims": [{"claim_id": "change", "claim": "The notice describes the reporting change.",
                "source_ids": ["agency"], "evidence_excerpt": "The notice describes the reporting change and scope.",
                "verification_status": "unverified", "factual_state": "unverified"}],
            "fact_checked_at": "2026-10-30T11:00:00+09:00",
            "seo": {"search_intent": "Understand the policy update", "primary_terms": ["policy update"],
                "related_terms": [], "seo_title": "Understanding the policy update",
                "search_description": "An evidence-led guide to the policy update and the details readers should verify.",
                "core_question": "What changed?", "core_answer": "The article explains only the stated change."},
            "blogger_labels": [], "generation_method": "manual_codex_import", "model_name": "Codex Desktop",
            "generated_at": "2026-10-30T11:00:00+09:00", "created_by": "Codex Desktop automation-8",
        },
        "manual_origin": {"execution_mode": "manual", "automation_id": "automation-8",
            "manual_run_id": "codex-manual:automation-8:" + str(uuid4()), "session_id": session_id,
            "turn_trigger": "automation_cron_run_now", "invoked_at": "2026-10-30T23:17:22+09:00"},
    }
    payload["item"]["seo"]["search_description"] += " Additional"
    payload["manual_origin"]["manual_run_id"] = "codex-manual:automation-8:" + payload["manual_origin"]["manual_run_id"].rsplit(":", 1)[1]
    envelope = validate_envelope(json.dumps(payload).encode())
    assert isinstance(envelope, ManualAutomationImportEnvelope)
    assert envelope.manual_origin.execution_mode == "manual"
    bad = json.loads(json.dumps(payload))
    bad["item"]["generation_method"] = "chatgpt_scheduled_export"
    with pytest.raises(ValidationError):
        validate_envelope(json.dumps(bad).encode())
