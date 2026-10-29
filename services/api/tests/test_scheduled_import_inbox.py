from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from woori import content_imports, worker
from woori.config import settings
from woori.content_imports import ScheduledImportEnvelope, ScheduledImportOrigin
from woori.db import connection
from woori.main import app
from woori.scheduled_import_inbox import process_inbox_once, validate_envelope


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
        "market_close_kr", "market_close_jp", "market_close_cn", "market_close_us", "weekly_finance", "trends_major_issue",
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


def test_scheduled_envelope_requires_taxonomy_labels_and_imported_parent_for_revision() -> None:
    valid_json = json.dumps(scheduled_payload(), ensure_ascii=False).encode("utf-8")
    allowed = validate_envelope(valid_json)
    assert allowed == ScheduledImportEnvelope.model_validate_json(valid_json)
    assert allowed.item.blogger_labels == content_imports.suggested_labels(
        "stocks", "ko", google_trends_based=False
    )
    forbidden = scheduled_payload()
    forbidden["item"]["blogger_labels"] = ["주식", "임의라벨"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="unrecognized_or_unreviewed_blogger_label"):
        validate_envelope(json.dumps(forbidden, ensure_ascii=False).encode("utf-8"))

    unregistered_revision = scheduled_payload()
    unregistered_revision["item"].update({  # type: ignore[union-attr]
        "content_id": "scheduled-revision-unregistered-parent",
        "parent_content_id": "never-imported-parent",
        "relation": "revision",
    })
    # Shape validation accepts the relation. The API's DB-backed check must reject it.
    assert ScheduledImportEnvelope.model_validate(unregistered_revision).item.relation == "revision"


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
            origin = json.loads(request.content)
            assert origin["task_id"] == "woori-market-close-kr"
            assert origin["inbox_file_name"] == source.name
            assert len(origin["inbox_file_sha256"]) == 64
            return httpx.Response(201, json={"audit_event_id": 77, "duplicate": False,
                                             "provenance_verified": False, "auto_publication_enabled": False})
        if request.url.path.endswith("/live-source-evidence"):
            return httpx.Response(201, json={"outcomes": [{"status": "not_in_reviewed_catalog"}],
                                             "blogger_write_performed": False, "auto_eligible": False})
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
    assert result["results"][0]["file_sha256"]
    assert result["results"][0]["machine_assessment_passed"] is False
    assert result["results"][0]["independent_source_verification"] is False
    assert result["results"][0]["publish_ready"] is False
    assert result["results"][0]["source_evidence_capture"]["status"] == "recorded"
    assert result["blogger_writes"] == 0 and result["external_ai_calls"] == 0
    assert [call.method for call in calls] == ["POST", "POST", "POST", "GET", "POST"]
    assert not source.exists()
    assert list((tmp_path / "processed").glob("*.processing.json"))
    assert (tmp_path / "incoming").is_dir() and (tmp_path / "rejected").is_dir()


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


def test_inbox_records_exact_safe_pydantic_validation_reason(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    ready.mkdir()
    payload = scheduled_payload()
    payload["item"]["blogger_labels"] = ["허용되지 않은 라벨"]  # type: ignore[index]
    source = ready / "invalid-label.ready.json"
    original = json.dumps(payload, ensure_ascii=False)
    source.write_text(original, encoding="utf-8")

    result = process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32,
                                transport=httpx.MockTransport(lambda _: pytest.fail("invalid envelope must not call API")))
    outcome = result["results"][0]
    assert outcome["status"] == "quarantined"
    assert outcome["reason"] == "invalid_envelope"
    assert outcome["http_status"] is None
    assert any(error["type"] == "value_error" and "unrecognized_or_unreviewed_blogger_label" in error["message"]
               for error in outcome["validation_errors"])
    assert (tmp_path / "quarantine" / "invalid-label.processing.json").read_text(encoding="utf-8") == original


def test_inbox_records_http_status_and_sanitized_api_detail(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    ready.mkdir()
    source = ready / "missing-parent.ready.json"
    payload = scheduled_payload()
    payload["item"].update({  # type: ignore[union-attr]
        "content_id": "scheduled-revision-with-missing-parent",
        "parent_content_id": "unregistered-parent-0001",
        "relation": "revision",
    })
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def reject(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "The referenced parent import does not exist; token=abc123"})

    result = process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32,
                                transport=httpx.MockTransport(reject))
    outcome = result["results"][0]
    assert outcome["status"] == "rejected"
    assert outcome["reason"] == "api_rejected"
    assert outcome["http_status"] == 409
    assert outcome["api_error"] == "The referenced parent import does not exist; token=[redacted]"
    assert not source.exists()
    assert (tmp_path / "rejected" / "missing-parent.processing.json").exists()


def test_inbox_requeues_transient_failure_and_recovers_interrupted_processing(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    processing = tmp_path / "processing"
    ready.mkdir()
    processing.mkdir()
    interrupted = processing / "interrupted.processing.json"
    interrupted.write_text(
        json.dumps(scheduled_payload()), encoding="utf-8"
    )
    os.utime(interrupted, (0, 0))
    active = processing / "active.processing.json"
    active.write_text(json.dumps(scheduled_payload()), encoding="utf-8")
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
    assert active.exists()


def test_inbox_refuses_operations_port_without_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit_confirmation"):
        process_inbox_once(tmp_path, "http://127.0.0.1:8100", "x" * 32)


def test_inbox_limits_files_and_rejects_non_loopback_api(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between_1_and_4"):
        process_inbox_once(tmp_path, "http://127.0.0.1:18100", "x" * 32, max_files=5)
    with pytest.raises(ValueError, match="loopback"):
        process_inbox_once(tmp_path, "http://example.com:18100", "x" * 32)


def test_local_inbox_import_and_duplicate_use_isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with connection() as conn, conn.transaction(force_rollback=True):
        @contextmanager
        def shared():
            with conn.transaction():
                yield conn

        monkeypatch.setattr(content_imports, "connection", shared)
        blog = conn.execute(
            """INSERT INTO blogger_blogs(language_code,url,display_name,blog_id)
            VALUES ('ko','https://scheduled-import-test.blogspot.com','Scheduled import test blog','9991230000000000001')
            RETURNING blog_id,url"""
        ).fetchone()
        assert blog
        api_responses: list[tuple[int, bytes]] = []

        def app_transport(request: httpx.Request) -> httpx.Response:
            response = client.request(
                request.method,
                request.url.path + ("?" + request.url.query.decode() if request.url.query else ""),
                headers={key: request.headers[key] for key in ("authorization", "content-type") if key in request.headers},
                content=request.content,
            )
            api_responses.append((response.status_code, response.content))
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)

        with TestClient(app) as client:
            root = tmp_path / ".local" / "gpt-scheduled-import"
            payload = scheduled_payload()
            origin = payload["scheduled_origin"]
            assert isinstance(origin, dict)
            origin["target_blog_id"] = blog["blog_id"]
            origin["target_blog_url"] = blog["url"]
            for index, occurrence in enumerate(("woori-market-close-kr-20261028-01", "woori-market-close-kr-20261028-02")):
                origin["occurrence_id"] = occurrence
                source = root / "incoming" / f"integration-ko-{index}.part"
                source.parent.mkdir(parents=True, exist_ok=True)
                staging = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                source.write_bytes(staging)
                ready = root / "ready" / f"integration-ko-{index}.ready.json"
                ready.parent.mkdir(parents=True, exist_ok=True)
                source.replace(ready)
                result = process_inbox_once(
                    root,
                    "http://127.0.0.1:18100",
                    settings().admin_token,
                    transport=httpx.MockTransport(app_transport),
                )
                error_details = json.loads(api_responses[-1][1]).get("detail", [])
                safe_errors = [(entry.get("loc"), entry.get("msg")) for entry in error_details]
                assert result["results"][0]["status"] == "imported", (result["results"][0], safe_errors)
                assert result["results"][0]["publish_ready"] is False
                assert result["blogger_writes"] == 0
                assert result["results"][0]["duplicate"] is (index == 1)
            missing_parent = scheduled_payload()
            missing_parent["item"].update({  # type: ignore[union-attr]
                "content_id": "scheduled-missing-parent-e2e",
                "parent_content_id": "not-imported-parent-e2e",
                "relation": "revision",
            })
            missing_parent_response = client.post(
                "/admin/research/content-imports", json={"submitted_by": "test scheduled import", "item": missing_parent["item"]},
                headers={"Authorization": f"Bearer {settings().admin_token}"},
            )
            assert missing_parent_response.status_code == 409
            assert missing_parent_response.json()["detail"] == "The referenced parent import does not exist"
            corrected_original = scheduled_payload()
            corrected_original["item"].update({  # type: ignore[union-attr]
                "content_id": "scheduled-corrected-before-first-import",
                "parent_content_id": None,
                "relation": "original",
            })
            corrected_response = client.post(
                "/admin/research/content-imports",
                json={"submitted_by": "test scheduled import", "item": corrected_original["item"]},
                headers={"Authorization": f"Bearer {settings().admin_token}"},
            )
            assert corrected_response.status_code == 201, corrected_response.text

            different_content_same_occurrence = scheduled_payload()
            different_content_same_occurrence["item"]["content_id"] = "scheduled-same-occurrence-new-content"  # type: ignore[index]
            imported_response = client.post(
                "/admin/research/content-imports",
                json={"submitted_by": "test scheduled import", "item": different_content_same_occurrence["item"]},
                headers={"Authorization": f"Bearer {settings().admin_token}"},
            )
            assert imported_response.status_code == 201, imported_response.text
            duplicate_origin = dict(origin)
            duplicate_origin["occurrence_id"] = "woori-market-close-kr-20261028-01"
            duplicate_origin["target_blog_id"] = blog["blog_id"]
            duplicate_origin["target_blog_url"] = blog["url"]
            duplicate_origin_response = client.post(
                f"/admin/research/content-imports/{imported_response.json()['import_id']}/scheduled-origin",
                json=duplicate_origin,
                headers={"Authorization": f"Bearer {settings().admin_token}"},
            )
            assert duplicate_origin_response.status_code == 409
            assert "already recorded" in duplicate_origin_response.json()["detail"]
            imports = conn.execute(
                "SELECT count(*)::int AS count FROM external_content_imports WHERE external_content_id=%s",
                (payload["item"]["content_id"],),
            ).fetchone()
            origins = conn.execute(
                """SELECT count(*)::int AS count FROM audit_events
                WHERE event_type='content.import.scheduled_origin_recorded'
                  AND payload->>'inbox_file_sha256' IS NOT NULL"""
            ).fetchone()
            assert imports["count"] == 1
            assert origins["count"] == 2


def test_worker_inbox_tick_records_sanitized_file_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[tuple[str, object]] = []

    class FakeResult:
        def __init__(self, row: dict[str, bool]) -> None:
            self.row = row

        def fetchone(self) -> dict[str, bool]:
            return self.row

    class FakeConnection:
        def execute(self, query: str, params: object = None) -> FakeResult:
            statements.append((query, params))
            row = {"acquired": True} if "pg_try_advisory_lock" in query else {"unlocked": True}
            return FakeResult(row)

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(worker, "connection", fake_connection)
    monkeypatch.setattr(worker, "settings", lambda: SimpleNamespace(admin_token="x" * 32))
    monkeypatch.setattr(
        worker.scheduled_import_inbox,
        "process_inbox_once",
        lambda *args, **kwargs: {
            "processed_count": 1,
            "results": [{
                "file_key": "abc123", "file_sha256": "a" * 64, "status": "imported",
                "import_id": "import-1", "audit_event_id": 77, "duplicate": False,
                "machine_assessment_passed": False,
                "independent_source_verification": False, "publish_ready": False,
                "http_status": 409, "api_error": "parent does not exist",
                "validation_errors": [{"type": "value_error", "message": "safe detail"}],
            }],
            "blogger_writes": 0,
        },
    )

    result = worker.scheduled_import_intake_tick()

    assert result["processed_count"] == 1
    assert len(statements) == 3
    query, params = statements[-1]
    assert "scheduled_import.file_outcome" in query
    payload = params[0].obj
    assert payload["file_sha256"] == "a" * 64
    assert payload["publish_ready"] is False
    assert payload["blogger_writes"] == 0
    assert payload["http_status"] == 409
    assert payload["api_error"] == "parent does not exist"
    assert payload["validation_errors"][0]["message"] == "safe detail"
    assert "title" not in payload and "body" not in payload
    assert any("pg_try_advisory_lock" in query for query, _ in statements)
    assert any("pg_advisory_unlock" in query for query, _ in statements)


def test_worker_inbox_tick_skips_when_another_worker_owns_database_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        def fetchone(self) -> dict[str, bool]:
            return {"acquired": False}

    class FakeConnection:
        def execute(self, query: str, _params: object = None) -> FakeResult:
            assert "pg_try_advisory_lock" in query
            return FakeResult()

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    def must_not_process(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("the inbox must not be processed without the database claim")

    monkeypatch.setattr(worker, "connection", fake_connection)
    monkeypatch.setattr(worker, "settings", lambda: SimpleNamespace(admin_token="x" * 32))
    monkeypatch.setattr(worker.scheduled_import_inbox, "process_inbox_once", must_not_process)

    result = worker.scheduled_import_intake_tick()

    assert result["skipped"] == "another_worker_holds_inbox_lock"
