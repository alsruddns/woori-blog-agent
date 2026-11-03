from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from woori.automation_invocation import (
    _read_current_automation_start,
    _read_invocation_events,
    current_automation_id,
    resolve_current_invocation,
)
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
    turn_id = str(uuid4())
    records = [
        {"type": "session_meta", "payload": {"session_id": session_id, "id": session_id,
         "originator": "Codex Desktop", "thread_source": "automation", "cwd": str(project)}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn_id,
         "started_at": started_at.timestamp(),
         "turn_attribution": {"turn_id": turn_id, "turn_trigger": trigger}}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "Automation: Test\nAutomation ID: automation-8\nTask code: politics-kr."}]}},
    ]
    if quota_failure:
        records.append({"type": "event_msg", "payload": {"type": "task_complete",
            "turn_id": turn_id,
            "error": {"codex_error_info": "usage_limit_exceeded"}}})
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


def _append_turn(
    path: Path, *, turn_id: str, started_at: datetime, trigger: str,
    automation_id: str = "automation-8", include_prompt: bool = True,
) -> None:
    records = [{"type": "event_msg", "payload": {
        "type": "task_started", "turn_id": turn_id, "started_at": started_at.timestamp(),
        "turn_attribution": {"turn_id": turn_id, "turn_trigger": trigger},
    }}]
    if include_prompt:
        records.append({"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": f"Automation ID: {automation_id}"}]}})
    with path.open("a", encoding="utf-8") as output:
        output.write("".join(json.dumps(row) + "\n" for row in records))


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


def test_reused_desktop_thread_resolves_latest_official_run_now_turn(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    automations = codex / "automations"
    _write_automation(automations, project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    session = sessions / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled", quota_failure=True)
    current_turn_id = str(uuid4())
    _append_turn(session, turn_id=current_turn_id,
                 started_at=datetime(2026, 10, 30, 14, 17, 22, tzinfo=UTC),
                 trigger="automation_cron_run_now")

    result = resolve_current_invocation(
        "automation-8", project_root=project,
        environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(codex),
                 "CODEX_TURN_ID": current_turn_id},
    )

    assert result["execution_mode"] == "manual"
    assert result["trigger"] == "automation_cron_run_now"
    assert result["session_id"] == session_id


def test_latest_completed_event_cannot_be_reused_as_current_invocation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    _write_automation(codex / "automations", project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    session = sessions / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled", quota_failure=True)
    with pytest.raises(ValueError, match="current_automation_run_not_active"):
        resolve_current_invocation(
            "automation-8", project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(codex)},
        )


def test_multiple_unfinished_start_events_are_ambiguous_and_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    _write_automation(codex / "automations", project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    session = sessions / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    _append_turn(session, turn_id=str(uuid4()),
                 started_at=datetime(2026, 10, 30, 11, 58, 25, tzinfo=UTC),
                 trigger="automation_cron_run_now")
    with pytest.raises(ValueError, match="current_automation_start_event_ambiguous"):
        resolve_current_invocation(
            "automation-8", project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(codex)},
        )


def test_duplicate_start_event_for_same_turn_is_ambiguous(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    _write_automation(codex / "automations", project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    session = sessions / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    records = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    start = next(record for record in records if record.get("payload", {}).get("type") == "task_started")
    with session.open("a", encoding="utf-8") as output:
        output.write(json.dumps(start) + "\n")
    with pytest.raises(ValueError, match="current_automation_start_event_ambiguous"):
        resolve_current_invocation(
            "automation-8", project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(codex)},
        )


def test_composer_turn_with_automation_text_is_not_an_official_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    _write_automation(codex / "automations", project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    session = sessions / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled", quota_failure=True)
    _append_turn(session, turn_id=str(uuid4()),
                 started_at=datetime(2026, 10, 30, 14, 17, 22, tzinfo=UTC),
                 trigger="composer")
    with pytest.raises(ValueError, match="current_automation_trigger_unrecognized"):
        resolve_current_invocation(
            "automation-8", project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(codex)},
        )


def test_start_event_delay_gets_only_bounded_rereads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from woori import automation_invocation

    session = tmp_path / "session.jsonl"
    delayed = [True]
    reads = 0
    original_read = automation_invocation._read_invocation_events

    def read(path: Path) -> list[dict[str, object]]:
        nonlocal reads
        reads += 1
        records = original_read(path)
        if delayed[0]:
            delayed[0] = False
            return [record for record in records if not (
                record.get("type") == "event_msg"
                and record.get("payload", {}).get("type") == "task_started"
            )]
        return records

    project = tmp_path / "project"
    project.mkdir()
    session_id = str(uuid4())
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    sleeps: list[float] = []
    monkeypatch.setattr(automation_invocation, "_read_invocation_events", read)
    monkeypatch.setattr(automation_invocation.time, "sleep", sleeps.append)

    automation_id, start = _read_current_automation_start(session)

    assert automation_id == "automation-8"
    assert start["type"] == "task_started"
    assert reads == 2
    assert sleeps == [0.15]


def test_invocation_reader_streams_only_session_identity_events(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    session_id = str(uuid4())
    session = tmp_path / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    with session.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": [{"text": "old context"}],
        }}) + "\n")

    records = _read_invocation_events(session)

    assert [record["type"] for record in records] == [
        "session_meta", "event_msg", "response_item",
    ]
    prompt = records[-1]["payload"]["content"]
    assert prompt == [{"text": "Automation ID: automation-8"}]


def test_missing_start_event_uses_bounded_rereads_then_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import automation_invocation

    project = tmp_path / "project"
    project.mkdir()
    session_id = str(uuid4())
    session = tmp_path / f"rollout-{session_id}.jsonl"
    _session(session, session_id=session_id, project=project,
             started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    records = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    session.write_text(
        "".join(json.dumps(record) + "\n" for record in records
               if record.get("payload", {}).get("type") != "task_started"),
        encoding="utf-8",
    )
    sleeps: list[float] = []
    monkeypatch.setattr(automation_invocation.time, "sleep", sleeps.append)

    with pytest.raises(ValueError, match="current_automation_start_event_not_found"):
        _read_current_automation_start(session)
    assert sleeps == [0.15, 0.15, 0.15]


def test_current_turn_id_must_match_transcript_event(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    _write_automation(codex / "automations", project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    _session(sessions / f"rollout-{session_id}.jsonl", session_id=session_id,
             project=project, started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    with pytest.raises(ValueError, match="current_codex_turn_id_mismatch"):
        resolve_current_invocation(
            "automation-8", project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(codex),
                     "CODEX_TURN_ID": str(uuid4())},
        )


def test_current_automation_id_comes_from_exact_desktop_session_prompt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    _session(
        sessions / f"rollout-{session_id}.jsonl",
        session_id=session_id,
        project=project,
        started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
        trigger="automation_cron_scheduled",
    )
    assert current_automation_id(
        project_root=project,
        environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(tmp_path / ".codex")},
    ) == "automation-8"


def test_desktop_user_profile_default_is_used_when_codex_home_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex = tmp_path / ".codex"
    automations = codex / "automations"
    _write_automation(automations, project)
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    _session(sessions / f"rollout-{session_id}.jsonl", session_id=session_id,
             project=project, started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
             trigger="automation_cron_scheduled")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    environment = {"CODEX_THREAD_ID": session_id}

    assert current_automation_id(project_root=project, environ=environment) == "automation-8"
    result = resolve_current_invocation("automation-8", project_root=project, environ=environment)
    assert result["execution_mode"] == "scheduled"
    assert result["occurrence_id"] == "codex-slot:automation-8:20261030T2000KST"
    assert result["provenance_self_reported"] is True


def test_desktop_user_profile_default_still_fails_closed_without_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    with pytest.raises(ValueError, match="current_codex_session_record_missing_or_ambiguous"):
        current_automation_id(project_root=project, environ={"CODEX_THREAD_ID": str(uuid4())})


def test_current_automation_id_fails_when_session_has_multiple_ids(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    session_id = str(uuid4())
    session = sessions / f"rollout-{session_id}.jsonl"
    _session(
        session,
        session_id=session_id,
        project=project,
        started_at=datetime(2026, 10, 30, 10, 58, 25, tzinfo=UTC),
        trigger="automation_cron_scheduled",
    )
    with session.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{
                "type": "input_text", "text": "Automation ID: automation-9",
            }],
        }}) + "\n")
    with pytest.raises(ValueError, match="current_session_automation_id_missing_or_ambiguous"):
        current_automation_id(
            project_root=project,
            environ={"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(tmp_path / ".codex")},
        )


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
