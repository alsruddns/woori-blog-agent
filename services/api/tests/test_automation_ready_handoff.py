from __future__ import annotations

import json
from uuid import uuid4

import pytest
from woori.automation_ready_handoff import (
    handoff_incoming,
    invocation_matches,
    preflight_allows_import,
)
from woori.content_imports import ManualAutomationImportEnvelope
from woori.scheduled_import_inbox import validate_envelope


def _manual_payload(language: str) -> dict:
    session_id = str(uuid4())
    manual_run_id = f"codex-manual:automation-8:{uuid4()}"
    return {
        "schema_version": "woori-manual-automation-content-import/1.0",
        "submitted_by": "Codex Desktop automation-8 manual run",
        "item": {
            "schema_version": "1.0",
            "content_id": str(uuid4()),
            "event_group_id": f"event-{language}-20261104",
            "parent_content_id": None,
            "relation": "original",
            "source_region": "KR",
            "language_code": language,
            "target_audiences": [
                {
                    "language_code": language,
                    "target_region": "KR",
                    "reader_relevance_reason": "The reviewed issue provides relevant context for local readers.",
                }
            ],
            "title": "Evidence based article on the documented public update",
            "body_markdown": "## Documented update\n\n"
            + "The agency notice describes the update and its stated timing. [source:agency]\n\n"
            * 3,
            "category": "policy",
            "google_trends_based": False,
            "source_ids": ["agency"],
            "sources": [
                {
                    "source_id": "agency",
                    "title": "Public notice",
                    "organization": "Public agency",
                    "url": "https://example.gov/policy",
                    "observed_at": "2026-11-04T10:00:00+09:00",
                    "language_code": language,
                    "source_type": "government",
                    "rights_status": "quotation_review_required",
                    "rights_note": "Review quotation scope.",
                }
            ],
            "claims": [
                {
                    "claim_id": "update",
                    "claim": "The notice describes an update.",
                    "source_ids": ["agency"],
                    "evidence_excerpt": "The notice describes the update.",
                    "verification_status": "unverified",
                    "factual_state": "unverified",
                }
            ],
            "fact_checked_at": "2026-11-04T10:00:00+09:00",
            "seo": {
                "search_intent": "Understand the documented update",
                "primary_terms": ["policy update"],
                "related_terms": [],
                "seo_title": "Documented policy update explained",
                "search_description": "An evidence-led summary of the documented update and its stated timing.",
                "core_question": "What changed?",
                "core_answer": "The notice describes the stated update.",
            },
            "blogger_labels": [],
            "generation_method": "manual_codex_import",
            "model_name": "Codex Desktop",
            "generated_at": "2026-11-04T10:00:00+09:00",
            "created_by": "Codex Desktop automation-8",
        },
        "manual_origin": {
            "execution_mode": "manual",
            "automation_id": "automation-8",
            "manual_run_id": manual_run_id,
            "session_id": session_id,
            "turn_trigger": "automation_cron_run_now",
            "invoked_at": "2026-11-04T10:00:00+09:00",
        },
    }


def _scheduled_payload() -> dict:
    payload = _manual_payload("ko")
    payload["schema_version"] = "woori-scheduled-content-import/1.0"
    item = payload["item"]
    item["generation_method"] = "chatgpt_scheduled_export"
    del payload["manual_origin"]
    payload["scheduled_origin"] = {
        "task_type": "scheduled_article",
        "task_id": "automation-8",
        "occurrence_id": "codex-slot:automation-8:20261104T1000KST",
        "occurrence_id_source": "project_derived_kst_slot",
        "scheduler_occurrence_id": None,
        "automation_id": "automation-8",
        "scheduled_slot": "2026-11-04T10:00:00+09:00",
        "executed_at": "2026-11-04T10:00:00+09:00",
        "target_language_code": "ko",
        "target_blog_id": "1234567890123456789",
        "target_blog_url": "https://trend-ko.blogspot.com",
        "source_as_of": "2026-11-04T09:50:00+09:00",
        "local_duplicate_status": "not_found",
        "remote_duplicate_status": "not_checked",
        "draft_import_allowed": True,
        "publication_recheck_required": True,
        "publication_retry_status": "required_before_publication",
    }
    return payload


@pytest.mark.parametrize("language", ["ko", "en", "ja", "de", "pt-BR", "vi"])
def test_clear_manual_run_is_atomically_handed_off_for_active_locales(
    tmp_path, language: str
) -> None:
    root = tmp_path / "gpt-scheduled-import"
    incoming = root / "incoming"
    incoming.mkdir(parents=True)
    payload = _manual_payload(language)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    source = incoming / f"article-{language}.part"
    source.write_bytes(raw)
    envelope = validate_envelope(raw)
    assert isinstance(envelope, ManualAutomationImportEnvelope)
    origin = envelope.manual_origin
    invocation = {
        "execution_mode": "manual",
        "trigger": "automation_cron_run_now",
        "automation_id": origin.automation_id,
        "session_id": str(origin.session_id),
        "manual_run_id": origin.manual_run_id,
        "manual_origin": origin.model_dump(mode="json", exclude_none=True),
    }
    preflight = {
        "local_status": "not_found",
        "draft_import_allowed": True,
        "remote_status": "not_checked",
    }

    result = handoff_incoming(root, source, invocation=invocation, preflight=preflight)

    ready = root / "ready" / f"article-{language}.ready.json"
    assert result["handed_off"] is True
    assert result["execution_mode"] == "manual"
    assert ready.read_bytes() == raw
    assert not source.exists()
    assert result["publication_created"] is False
    assert result["blogger_write_count"] == 0


def test_handoff_refuses_unverified_trigger_duplicate_and_existing_ready(tmp_path) -> None:
    root = tmp_path / "gpt-scheduled-import"
    incoming = root / "incoming"
    incoming.mkdir(parents=True)
    payload = _manual_payload("en")
    raw = json.dumps(payload).encode()
    source = incoming / "same.part"
    source.write_bytes(raw)
    envelope = validate_envelope(raw)
    origin = envelope.manual_origin
    invocation = {
        "execution_mode": "manual",
        "trigger": "composer",
        "automation_id": origin.automation_id,
        "session_id": str(origin.session_id),
        "manual_run_id": origin.manual_run_id,
        "manual_origin": origin.model_dump(mode="json", exclude_none=True),
    }
    clear = {
        "local_status": "not_found",
        "draft_import_allowed": True,
        "remote_status": "not_checked",
    }
    assert not invocation_matches(envelope, invocation)
    assert preflight_allows_import(clear)
    assert not preflight_allows_import({**clear, "local_status": "unknown"})
    assert not preflight_allows_import({**clear, "draft_import_allowed": False})
    assert not preflight_allows_import({**clear, "remote_status": "found"})
    with pytest.raises(ValueError, match="invocation_mismatch"):
        handoff_incoming(root, source, invocation=invocation, preflight=clear)
    good = {**invocation, "trigger": "automation_cron_run_now"}
    (root / "ready").mkdir(exist_ok=True)
    (root / "ready" / "same.ready.json").write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        handoff_incoming(root, source, invocation=good, preflight=clear)
    assert source.read_bytes() == raw
    assert (root / "ready" / "same.ready.json").read_bytes() == b"existing"


def test_verified_scheduled_occurrence_handoff_preserves_slot_identity(tmp_path) -> None:
    root = tmp_path / "gpt-scheduled-import"
    incoming = root / "incoming"
    incoming.mkdir(parents=True)
    payload = _scheduled_payload()
    raw = json.dumps(payload).encode()
    source = incoming / "scheduled.part"
    source.write_bytes(raw)
    envelope = validate_envelope(raw)
    origin = envelope.scheduled_origin
    invocation = {
        "execution_mode": "scheduled",
        "trigger": "automation_cron_scheduled",
        "automation_id": origin.automation_id,
        "occurrence_id": origin.occurrence_id,
        "scheduled_slot": origin.scheduled_slot.isoformat(),
    }

    result = handoff_incoming(
        root,
        source,
        invocation=invocation,
        preflight={
            "local_status": "not_found",
            "draft_import_allowed": True,
            "remote_status": "not_checked",
        },
    )

    saved = json.loads((root / "ready" / "scheduled.ready.json").read_text(encoding="utf-8"))
    assert result["execution_mode"] == "scheduled"
    assert saved["scheduled_origin"]["occurrence_id"] == "codex-slot:automation-8:20261104T1000KST"
    assert saved["scheduled_origin"]["scheduled_slot"] == "2026-11-04T10:00:00+09:00"
