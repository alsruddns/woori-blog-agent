from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from woori.content_imports import ScheduledImportEnvelope, ScheduledImportOrigin
from woori.scheduled_import_inbox import process_inbox_once


def scheduled_payload(**updates: object) -> dict[str, object]:
    item: dict[str, object] = {
        "schema_version": "1.0",
        "content_id": "scheduled-kr-close-20261028-001",
        "event_group_id": "kr-market-close-20261028",
        "research_package_id": None,
        "parent_content_id": None,
        "relation": "original",
        "source_region": "KR",
        "language_code": "ko",
        "target_audiences": [{"language_code": "ko", "target_region": "KR",
                              "reader_relevance_reason": "The market report is written for Korean investors and readers."}],
        "title": "한국 주식시장 마감과 업종별 흐름 분석",
        "body_markdown": "## 시장의 핵심 흐름\n\n" + ("공식 자료로 확인된 지수와 시장 배경을 설명합니다. " * 8),
        "category": "stocks",
        "google_trends_based": False,
        "source_ids": ["src-exchange-close"],
        "sources": [{"source_id": "src-exchange-close", "title": "Official exchange closing data",
                     "organization": "Example Exchange", "url": "https://example.org/market",
                     "published_at": "2026-10-28T06:30:00Z", "observed_at": "2026-10-28T08:00:00Z",
                     "language_code": "ko", "source_type": "statistical", "rights_status": "unknown",
                     "rights_note": "Redistribution rights require human review."}],
        "claims": [{"claim_id": "claim-close", "claim": "The official source reports the market closing level.",
                    "source_ids": ["src-exchange-close"], "evidence_excerpt": "The official source reports the market closing level and session date.",
                    "verification_status": "unverified", "factual_state": "unverified"}],
        "fact_checked_at": "2026-10-28T08:00:00Z",
        "seo": {"search_intent": "Understand the Korean stock market close",
                "primary_terms": ["Korean stock market close"], "related_terms": ["KOSPI", "KOSDAQ"],
                "seo_title": "Korean stock market close: session analysis",
                "search_description": "An evidence-led review of the latest Korean stock market session, its sector moves, and the data readers should verify.",
                "core_question": "What shaped the Korean stock market session?",
                "core_answer": "The article explains only the session details supported by its cited official sources."},
        "blogger_labels": ["주식"],
        "generation_method": "chatgpt_scheduled_export",
        "model_name": None,
        "generated_at": "2026-10-28T08:05:00Z",
        "created_by": "GPT Work scheduled export",
    }
    item.update(updates)
    return {
        "schema_version": "woori-scheduled-content-import/1.0",
        "submitted_by": "Scheduled export intake",
        "item": item,
        "scheduled_origin": {
            "task_type": "market_close_kr",
            "task_id": "woori-market-close-kr",
            "occurrence_id": "woori-market-close-kr-20261028-01",
            "executed_at": "2026-10-28T08:06:00Z",
            "market_date": "2026-10-28",
            "target_language_code": "ko",
            "target_blog_id": "1234567890123456789",
            "target_blog_url": "https://trend-ko.blogspot.com",
            "source_as_of": "2026-10-28T08:00:00Z",
        },
    }


def test_scheduled_envelope_requires_self_reported_task_and_consistent_target() -> None:
    payload = scheduled_payload()
    assert ScheduledImportEnvelope.model_validate(payload).scheduled_origin.market_date is not None
    root = Path(__file__).resolve().parents[3]
    contract = json.loads(
        (root / "docs/schemas/woori-scheduled-content-import-1.0.schema.json").read_text(encoding="utf-8")
    )
    assert contract["required"] == ["schema_version", "submitted_by", "item", "scheduled_origin"]
    assert contract["properties"]["item"]["$ref"].endswith("woori-content-import-1.0.schema.json#/properties/item")
    assert contract["properties"]["scheduled_origin"]["properties"]["task_type"]["enum"] == [
        "market_close_kr", "market_close_jp", "market_close_cn", "market_close_us", "weekly_finance",
    ]
    no_market_date = json.loads(json.dumps(payload))
    no_market_date["scheduled_origin"]["market_date"] = None
    with pytest.raises(ValidationError, match="market_close_requires_market_date"):
        ScheduledImportEnvelope.model_validate(no_market_date)
    wrong_language = json.loads(json.dumps(payload))
    wrong_language["scheduled_origin"]["target_language_code"] = "en"
    with pytest.raises(ValidationError, match="scheduled_target_language_mismatch"):
        ScheduledImportEnvelope.model_validate(wrong_language)
    wrong_market_language = json.loads(json.dumps(payload))
    wrong_market_language["item"]["language_code"] = "en"
    wrong_market_language["item"]["target_audiences"] = [{
        "language_code": "en", "target_region": "US",
        "reader_relevance_reason": "The market report is independently written for US market readers.",
    }]
    wrong_market_language["item"]["blogger_labels"] = ["Stocks"]
    wrong_market_language["scheduled_origin"]["target_language_code"] = "en"
    with pytest.raises(ValidationError, match="market_task_language_mismatch"):
        ScheduledImportEnvelope.model_validate(wrong_market_language)
    wrong_method = json.loads(json.dumps(payload))
    wrong_method["item"]["generation_method"] = "manual_codex_import"
    with pytest.raises(ValidationError, match="scheduled_envelope_requires_scheduled_export_method"):
        ScheduledImportEnvelope.model_validate(wrong_method)


def test_scheduled_origin_rejects_naive_time_and_unregistered_url_shape() -> None:
    payload = scheduled_payload()["scheduled_origin"]
    assert isinstance(payload, dict)
    invalid_time = dict(payload, executed_at="2026-10-28T08:06:00")
    with pytest.raises(ValidationError, match="scheduled_timestamp_requires_timezone"):
        ScheduledImportOrigin.model_validate(invalid_time)
    invalid_url = dict(payload, target_blog_url="https://example.org")
    with pytest.raises(ValidationError, match="registered_blogspot"):
        ScheduledImportOrigin.model_validate(invalid_url)


def test_inbox_posts_review_held_item_and_idempotent_origin_then_moves_file(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    ready.mkdir()
    source = ready / "kr-close-20261028.ready.json"
    source.write_text(json.dumps(scheduled_payload(), ensure_ascii=False), encoding="utf-8")
    calls: list[httpx.Request] = []
    import_id = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + ("x" * 32)
        if request.url.path.endswith("/scheduled-origin"):
            assert json.loads(request.content)["task_id"] == "woori-market-close-kr"
            return httpx.Response(201, json={"audit_event_id": 77, "duplicate": False,
                                             "provenance_verified": False, "auto_publication_enabled": False})
        if request.method == "GET":
            return httpx.Response(200, json={"latest_version": {"id": "version-1"}, "assessments": []})
        if request.url.path.endswith("/assessment"):
            return httpx.Response(201, json={"version_id": "version-1", "machine_passed": False,
                                             "independent_source_verification": False,
                                             "generation_ready": False, "publish_ready": False})
        payload = json.loads(request.content)
        assert payload["item"]["generation_method"] == "chatgpt_scheduled_export"
        return httpx.Response(201, json={"import_id": import_id, "duplicate": False,
                                         "state": "awaiting_human_review", "publish_ready": False})

    result = process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32,
                                transport=httpx.MockTransport(handler))
    assert result["processed_count"] == 1
    assert result["results"][0]["status"] == "imported"
    assert result["results"][0]["import_id"] == import_id
    assert result["results"][0]["audit_event_id"] == 77
    assert result["results"][0]["machine_assessment_passed"] is False
    assert result["results"][0]["independent_source_verification"] is False
    assert result["results"][0]["publish_ready"] is False
    assert result["blogger_writes"] == 0 and result["external_ai_calls"] == 0
    assert [call.method for call in calls] == ["POST", "POST", "GET", "POST"]
    assert not source.exists()
    assert list((tmp_path / "processed").glob("*.processing.json"))


def test_inbox_quarantines_invalid_and_ignores_incomplete_files(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    ready.mkdir()
    invalid = ready / "bad.ready.json"
    invalid.write_text('{"secret":"must-not-be-logged"}', encoding="utf-8")
    incomplete = ready / "draft.part"
    incomplete.write_text("{}", encoding="utf-8")
    network_calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(500)

    result = process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32,
                                transport=httpx.MockTransport(handler))
    assert network_calls == 0
    assert result["results"][0]["status"] == "quarantined"
    assert "must-not-be-logged" not in json.dumps(result)
    assert (tmp_path / "quarantine" / "bad.processing.json").exists()
    assert incomplete.exists()


def test_inbox_requeues_transient_failure_and_recovers_interrupted_processing(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    processing = tmp_path / "processing"
    ready.mkdir()
    processing.mkdir()
    (processing / "interrupted.processing.json").write_text(
        json.dumps(scheduled_payload()), encoding="utf-8"
    )
    source = ready / "offline.ready.json"
    source.write_text(json.dumps(scheduled_payload()), encoding="utf-8")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "secret response must not escape"})

    result = process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32,
                                transport=httpx.MockTransport(handler))
    assert result["recovered_processing_files"] == 1
    assert result["results"][0]["status"] == "ready"
    assert "secret response" not in json.dumps(result)
    assert source.exists()
    assert (ready / "interrupted.ready.json").exists()


def test_inbox_refuses_operations_port_without_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit_confirmation"):
        process_inbox_once(tmp_path, "http://127.0.0.1:8100", "x" * 32)


def test_inbox_limits_files_and_rejects_non_loopback_api(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between_1_and_4"):
        process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32, max_files=5)
    with pytest.raises(ValueError, match="loopback"):
        process_inbox_once(tmp_path, "http://example.com:18100", "x" * 32)
