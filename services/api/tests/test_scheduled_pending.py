import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from uuid import uuid4

import httpx
import pytest
from test_content_imports import valid_item
from test_pipeline import lab as shared_lab
from woori import content_imports
from woori import scheduled_pending as pending
from woori import scheduled_preflight as broker

from scripts.scheduled_duplicate_check import check_duplicate

lab = shared_lab
PATH = "/admin/research/content-imports/scheduled-recovery"
VERIFY_INVOCATION = pending.verify_saved_invocation


@pytest.fixture
def setup(lab, monkeypatch):
    conn, api, headers = lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(pending, "connection", shared)
    monkeypatch.setattr(content_imports, "connection", shared)
    monkeypatch.setattr(pending, "verify_configured_slot", lambda **kw: {"verified": True})
    monkeypatch.setattr(pending, "verify_saved_invocation", lambda *a: True)
    return conn, api, headers


def envelope():
    now = datetime.now(UTC)
    slot = now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    from woori.scheduled_occurrence import occurrence_metadata

    return {
        "schema_version": "woori-scheduled-content-import/1.0",
        "submitted_by": "isolated outage test",
        "item": valid_item(
            content_id=str(uuid4()),
            language_code="en",
            source_region="US",
            generation_method="chatgpt_scheduled_export",
            generated_at=now.isoformat(),
            fact_checked_at=now.isoformat(),
        ),
        "scheduled_origin": {
            "task_type": "scheduled_article",
            "task_id": "isolated-scheduled-test",
            **occurrence_metadata(automation_id="automation-5", scheduled_slot=slot),
            "executed_at": now.isoformat(),
            "source_as_of": now.isoformat(),
            "target_language_code": "en",
            "target_blog_id": "1234567890123456789",
            "target_blog_url": "https://trend-en.blogspot.com",
            "local_duplicate_status": "unknown",
            "remote_duplicate_status": "not_checked",
            "draft_import_allowed": False,
            "publication_recheck_required": True,
            "publication_retry_status": "required_before_publication",
        },
    }


def register(conn):
    conn.execute("""INSERT INTO blogger_blogs(language_code,url,blog_id,display_name,active)
        VALUES('en','https://trend-en.blogspot.com','1234567890123456789','isolated recovery',true)
        ON CONFLICT DO NOTHING""")


def body(data):
    import hashlib

    raw = json.dumps(data).encode()
    return {"manuscript_utf8": raw.decode(), "manuscript_sha256": hashlib.sha256(raw).hexdigest()}


def test_recovery_requires_actual_session_evidence(setup, monkeypatch):
    _, api, headers = setup
    monkeypatch.setattr(pending, "verify_saved_invocation", VERIFY_INVOCATION)
    data = envelope()
    result = api.post(PATH, headers=headers, json=body(data))
    assert result.json()["status"] == "review_required"
    assert result.json()["reason"] == "actual_invocation_unverified"


def test_slot_config_is_not_a_trigger_and_old_slot_cannot_be_current_execution(monkeypatch):
    from woori.scheduled_import_inbox import validate_envelope

    data = envelope()
    parsed = validate_envelope(json.dumps(data).encode())
    session = str(uuid4())
    actual = {
        "execution_mode": "scheduled",
        "occurrence_id": data["scheduled_origin"]["occurrence_id"],
        "executed_at": data["scheduled_origin"]["executed_at"],
    }
    monkeypatch.setattr(pending, "resolve_current_invocation", lambda *a, **kw: actual)
    assert VERIFY_INVOCATION(parsed, {"session_id": session}) is True
    actual["execution_mode"] = "manual"
    assert VERIFY_INVOCATION(parsed, {"session_id": session}) is False
    actual["execution_mode"] = "scheduled"
    actual["executed_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assert VERIFY_INVOCATION(parsed, {"session_id": session}) is False


def test_old_intake_can_recover_evidence_from_exact_pending_file(setup, monkeypatch, tmp_path):
    conn, api, headers = setup
    register(conn)
    data = envelope()
    evidence = {"session_id": str(uuid4())}
    monkeypatch.setattr(pending, "ROOT", tmp_path)
    pending.save_pending(
        tmp_path / ".local/gpt-scheduled-import", json.dumps(data).encode(), invocation=evidence
    )
    monkeypatch.setattr(
        pending, "verify_saved_invocation", lambda envelope, received: received == evidence
    )
    result = api.post(PATH, headers=headers, json=body(data))
    assert result.json()["status"] == "imported", result.text


def test_proxy_refused_uses_fixed_backend_broker():
    seen = []

    def refused(*a, **kw):
        raise URLError(ConnectionRefusedError())

    result = check_duplicate(
        {"stage": "generation"},
        opener=refused,
        fallback=lambda value: (
            seen.append(value)
            or {
                "status": "unknown",
                "draft_import_allowed": True,
                "local_status": "not_found",
                "lookup_route": "backend_api",
            }
        ),
    )
    assert result["lookup_route"] == "backend_api" and seen == [{"stage": "generation"}]
    assert result["dashboard_failure"]["attempts"] == 3


def test_auth_or_schema_rejection_never_falls_back():
    for status in (401, 403, 422):

        def rejected(*a, status=status, **kw):
            raise HTTPError("http://127.0.0.1:3100", status, "rejected", {}, None)

        check_duplicate(
            {"stage": "generation"},
            opener=rejected,
            fallback=lambda value: pytest.fail("must not bypass rejection"),
        )


def test_backend_direct_is_authenticated_loopback_and_never_publication(setup):
    def handler(request):
        assert (
            str(request.url)
            == "http://127.0.0.1:8100/admin/research/content-imports/duplicate-check"
        )
        assert request.headers["Authorization"].startswith("Bearer ")
        assert json.loads(request.content)["stage"] == "generation"
        return httpx.Response(
            200,
            json={"status": "unknown", "local_status": "not_found", "draft_import_allowed": True},
        )

    payload = {
        "stage": "generation",
        "language_code": "en",
        "target_country": "US",
        "target_blog_id": "1234567890123456789",
        "event_group_id": "isolated-event",
        "topic": "isolation recovery",
    }
    assert (
        broker.check_generation(payload, transport=httpx.MockTransport(handler))["lookup_route"]
        == "backend_api"
    )
    with pytest.raises(ValueError, match="generation_only"):
        broker.check_generation({**payload, "stage": "publication"})


def test_offline_save_is_immutable_and_does_not_import(setup, tmp_path):
    conn, _, _ = setup
    before = conn.execute("SELECT count(*) n FROM external_content_imports").fetchone()["n"]
    data = envelope()
    saved = pending.save_pending(tmp_path, json.dumps(data).encode())
    assert saved["status"] == "import_pending" and saved["duplicate_status"] == "pending"
    assert saved["run_id"] == data["scheduled_origin"]["occurrence_id"]
    assert saved["scheduler_occurrence_id"] is None
    assert pending.save_pending(tmp_path, json.dumps(data).encode())["path"] == saved["path"]
    data["item"]["title"] = "Different manuscript title for same occurrence"
    with pytest.raises(ValueError, match="payload_conflict"):
        pending.save_pending(tmp_path, json.dumps(data).encode())
    assert not list((tmp_path / "ready").glob("*"))
    assert conn.execute("SELECT count(*) n FROM external_content_imports").fetchone()["n"] == before


def test_recovery_import_is_atomic_idempotent_and_never_publishes(setup):
    conn, api, headers = setup
    register(conn)
    data = envelope()
    jobs = conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"]
    result = api.post(PATH, headers=headers, json=body(data))
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "imported", result.text
    assert result.json()["content_version_id"]
    assert api.post(PATH, headers=headers, json=body(data)).json() == result.json()
    changed = envelope()
    changed["item"]["title"] = "Another article in same occurrence"
    assert api.post(PATH, headers=headers, json=body(changed)).status_code == 409
    assert conn.execute("SELECT count(*) n FROM publishing_jobs").fetchone()["n"] == jobs
    assert result.json()["blogger_writes"] == 0


def test_stale_manuscript_preserves_slot_and_requires_review(setup):
    _, api, headers = setup
    data = envelope()
    slot = "2026-10-31T12:00:00+09:00"
    data["scheduled_origin"].update(
        {
            "scheduled_slot": slot,
            "occurrence_id": "codex-slot:automation-5:20261031T1200KST",
            "source_as_of": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
        }
    )
    result = api.post(PATH, headers=headers, json=body(data))
    assert result.json()["status"] == "review_required", result.text
    assert result.json()["run_id"] == "codex-slot:automation-5:20261031T1200KST"


def test_pending_outage_then_worker_recovery_without_ready_rewrite(setup, tmp_path):
    conn, api, headers = setup
    register(conn)
    data = envelope()
    saved = pending.save_pending(tmp_path, json.dumps(data).encode())

    def unavailable(request):
        raise httpx.ConnectError("isolated refusal")

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        result = pending.recover_pending_once(tmp_path, client)
    assert result[0]["status"] == "import_pending"
    assert not list((tmp_path / "pending_receipts").glob("*"))

    def server(request):
        response = api.request(
            request.method, request.url.path, headers=headers, json=json.loads(request.content)
        )
        return httpx.Response(response.status_code, json=response.json())

    with httpx.Client(
        base_url="http://127.0.0.1:8100", transport=httpx.MockTransport(server)
    ) as client:
        result = pending.recover_pending_once(tmp_path, client)
        assert result[0]["status"] == "imported", result
        assert pending.recover_pending_once(tmp_path, client) == []
    assert __import__("pathlib").Path(saved["path"]).exists()


def test_unknown_duplicate_blocks_import_and_request_requires_auth(setup, monkeypatch):
    conn, api, headers = setup
    data = envelope()
    monkeypatch.setattr(
        content_imports,
        "_scheduled_duplicate_check",
        lambda *a: {"local_status": "unknown", "draft_import_allowed": False},
    )
    assert api.post(PATH, json=body(data)).status_code == 401
    before = conn.execute("SELECT count(*) n FROM external_content_imports").fetchone()["n"]
    assert api.post(PATH, headers=headers, json=body(data)).json()["status"] == "import_pending"
    assert conn.execute("SELECT count(*) n FROM external_content_imports").fetchone()["n"] == before


def test_repository_fallback_reuses_generation_query(setup):
    conn, _, _ = setup
    register(conn)
    payload = {
        "stage": "generation",
        "language_code": "en",
        "target_country": "US",
        "target_blog_id": "1234567890123456789",
        "event_group_id": uuid4().hex,
        "topic": "Isolated repository fallback check",
    }

    def offline(request):
        raise httpx.ConnectError("isolated API outage")

    result = broker.check_generation(payload, transport=httpx.MockTransport(offline))
    assert result["lookup_route"] == "repository"
    assert result["local_status"] == "not_found" and result["draft_import_allowed"] is True
    assert result["remote_status"] == "not_checked"


def test_all_queries_unavailable_never_infer_absence(setup, monkeypatch, tmp_path):
    import psycopg

    monkeypatch.setattr(broker, "ROOT", tmp_path)

    def unavailable(*a, **kw):
        raise psycopg.OperationalError("must not leak credentials")

    monkeypatch.setattr(content_imports, "scheduled_duplicate_check", unavailable)
    payload = {
        "stage": "generation",
        "language_code": "en",
        "target_country": "US",
        "target_blog_id": "1234567890123456789",
        "event_group_id": uuid4().hex,
        "topic": "Isolated unavailable check",
    }
    result = broker.check_generation(
        payload, transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    assert result["local_status"] == "unknown" and result["draft_import_allowed"] is False
    assert result["research_allowed"] is True and result["import_status"] == "pending"
    assert "credentials" not in json.dumps(result)
    directory = tmp_path / ".local/gpt-scheduled-import/processed"
    directory.mkdir(parents=True)
    (directory / "prior.json").write_text(
        json.dumps(
            {
                "item": {"language_code": "en", "event_group_id": payload["event_group_id"]},
                "scheduled_origin": {"target_blog_id": payload["target_blog_id"]},
            }
        ),
        encoding="utf-8",
    )
    result = broker.check_generation(
        payload, transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    assert result["lookup_route"] == "preserved_index" and result["research_allowed"] is False
    assert result["draft_import_allowed"] is False


def test_origin_failure_rolls_back_entire_recovery(setup, monkeypatch):
    from fastapi import HTTPException

    conn, api, headers = setup
    register(conn)
    data = envelope()
    before = conn.execute("SELECT count(*) n FROM external_content_imports").fetchone()["n"]

    def fail(*a, **kw):
        raise HTTPException(409, "isolated origin conflict")

    monkeypatch.setattr(content_imports, "_record_scheduled_import_origin", fail)
    assert api.post(PATH, headers=headers, json=body(data)).status_code == 409
    assert conn.execute("SELECT count(*) n FROM external_content_imports").fetchone()["n"] == before


def test_manual_recovery_never_acquires_scheduled_provenance(setup, tmp_path):
    conn, api, headers = setup
    register(conn)
    scheduled = envelope()
    manual = {
        "schema_version": "woori-manual-automation-content-import/1.0",
        "submitted_by": scheduled["submitted_by"],
        "item": scheduled["item"],
        "manual_origin": {
            "execution_mode": "manual",
            "automation_id": "automation-5",
            "manual_run_id": f"codex-manual:automation-5:{uuid4()}",
            "session_id": str(uuid4()),
            "turn_trigger": "automation_cron_run_now",
            "invoked_at": datetime.now(UTC).isoformat(),
        },
    }
    manual["item"]["generation_method"] = "manual_codex_import"
    with pytest.raises(ValueError, match="requires_target"):
        pending.save_pending(tmp_path, json.dumps(manual).encode())
    saved = pending.save_pending(tmp_path, json.dumps(manual).encode(), "1234567890123456789")
    assert saved["execution_mode"] == "manual" and saved["scheduled_slot"] is None
    result = api.post(
        PATH, headers=headers, json={**body(manual), "target_blog_id": "1234567890123456789"}
    )
    assert result.json()["status"] == "imported", result.text
    assert result.json()["execution_mode"] == "manual"


def test_bad_hash_invalid_envelope_usage_error_and_unknown_automation_are_held(setup, monkeypatch):
    _, api, headers = setup
    data = envelope()
    bad = body(data)
    bad["manuscript_sha256"] = "0" * 64
    assert api.post(PATH, headers=headers, json=bad).status_code == 422
    assert (
        api.post(PATH, headers=headers, json=body({"error": "usage_limit_exceeded"})).status_code
        == 422
    )

    def invalid(**kw):
        raise ValueError("wrong saved slot")

    monkeypatch.setattr(pending, "verify_configured_slot", invalid)
    assert api.post(PATH, headers=headers, json=body(data)).status_code == 422


def test_unknown_duplicate_ready_file_is_saved_without_import(setup, tmp_path):
    from woori.scheduled_import_inbox import process_inbox_once

    data = envelope()
    ready = tmp_path / "ready"
    ready.mkdir()
    (ready / "isolated.ready.json").write_text(json.dumps(data), encoding="utf-8")
    result = process_inbox_once(
        tmp_path,
        "http://127.0.0.1:8100",
        "isolated-token-" + "x" * 32,
        transport=httpx.MockTransport(
            lambda request: pytest.fail("unknown uniqueness must not call Import")
        ),
        operations_target_confirmed=True,
    )
    assert result["results"][0]["status"] == "import_pending"
    assert len(list((tmp_path / "pending").glob("*.json"))) == 1


def test_same_event_other_slot_is_duplicate_skipped(setup):
    conn, api, headers = setup
    register(conn)
    data = envelope()
    first = api.post(PATH, headers=headers, json=body(data))
    assert first.json()["status"] == "imported"
    from woori.scheduled_occurrence import occurrence_metadata

    later = datetime.fromisoformat(data["scheduled_origin"]["scheduled_slot"]) + timedelta(days=1)
    data["scheduled_origin"].update(
        occurrence_metadata(automation_id="automation-5", scheduled_slot=later)
    )
    data["item"]["content_id"] = str(uuid4())
    second = api.post(PATH, headers=headers, json=body(data))
    assert second.json()["status"] == "duplicate_skipped", second.text
    assert second.json()["import_id"] == first.json()["import_id"]


def test_usage_limit_progress_sync_and_saved_manuscript_failure_is_pending(setup, tmp_path):
    _, api, headers = setup
    data = envelope()
    invocation = {**data["scheduled_origin"], "execution_mode": "scheduled"}
    usage = pending.record_progress(tmp_path, invocation, "usage_limit_waiting")
    assert usage["status"] == "usage_limit_waiting"
    assert not list((tmp_path / "pending").glob("*"))
    pending.save_pending(tmp_path, json.dumps(data).encode())
    saved = pending.record_progress(tmp_path, invocation, "failed")
    assert saved["status"] == "import_pending"
    response = api.post(
        "/admin/research/scheduled-manuscripts/progress", headers=headers, json=usage
    )
    assert response.status_code == 200, response.text
    assert (
        api.post(
            "/admin/research/scheduled-manuscripts/progress", headers=headers, json=usage
        ).json()["duplicate"]
        is True
    )
