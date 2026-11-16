from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from woori import blogger_writes, external_policy, publication_operation, publication_worker
from woori.db import connection
from woori.google_http import GoogleFailure
from woori.publication_modes import ModeSettingsInput, resolve_mode


def test_default_and_global_override():
    assert ModeSettingsInput().configured_mode == "manual"
    settings = [{"scope_type": "global", "scope_key": "", "configured_mode": "authoring_only"},
                {"scope_type": "blog", "scope_key": "b", "configured_mode": "auto"}]
    assert resolve_mode(settings, "ko", "b")["configured_mode"] == "authoring_only"
    assert resolve_mode([], "ko", "b")["configured_mode"] == "authoring_only"


def test_database_unavailable_fails_closed(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("database unavailable")
        yield
    monkeypatch.setattr(publication_operation, "connection", broken)
    assert not publication_operation.blogger_writes_allowed()


@pytest.mark.parametrize("method,operation,path", [
    ("POST", "blogger_draft_create", "/blogs/123/posts"),
    ("POST", "blogger_public_publish", "/blogs/123/posts/456/publish"),
    ("PATCH", "blogger_post_update", "/blogs/123/posts/456"),
    ("PUT", "blogger_post_update", "/blogs/123/posts/456"),
    ("DELETE", "blogger_post_update", "/blogs/123/posts/456"),
])
def test_all_wire_writes_zero_calls(method, operation, path, monkeypatch):
    calls = []
    monkeypatch.setattr(publication_operation, "blogger_writes_allowed", lambda: False)
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
    with pytest.raises(GoogleFailure, match="authoring_only"):
        blogger_writes._live_response(connection_id=uuid4(), operation=operation,
                                      method=method, path=path, transport=transport)
    with pytest.raises(external_policy.ExternalCallBlocked, match="authoring_only"):
        external_policy._authorize("google_blogger_read", operation,
            httpx.Request(method, "https://www.googleapis.com/blogger/v3" + path))
    assert calls == []


def test_restart_and_queues_untouched():
    from woori.trends_publication import enqueue_trends_auto_jobs
    with connection() as conn:
        before = conn.execute("SELECT id,status,retry_count FROM publishing_jobs ORDER BY id").fetchall()
    assert not publication_operation.blogger_writes_allowed()
    for _ in range(2):
        assert publication_worker.process_next_live_job(trends_auto_only=True) is None
        assert publication_worker.tick(allow_private_drafts=True, allow_live_publications=True,
            allow_scheduled_auto_publications=True, allow_manual_confirmed_publications=True,
            allow_trends_auto_publications=True) is None
        assert enqueue_trends_auto_jobs()["created"] == 0
        assert publication_worker.enqueue_scheduled_auto_jobs()["created"] == 0
    with connection() as conn:
        after = conn.execute("SELECT id,status,retry_count FROM publishing_jobs ORDER BY id").fetchall()
    assert before == after


def test_resume_requires_new_operations_approval():
    from fastapi import HTTPException
    from woori.publications import save_mode_settings
    with pytest.raises(HTTPException) as exc:
        save_mode_settings(ModeSettingsInput(configured_mode="auto", allowed_categories=["technology"]))
    assert exc.value.status_code == 409


@pytest.mark.parametrize("mode", ["draft", "publish"])
def test_manual_confirmation_matches_requested_mode(mode):
    from pydantic import ValidationError
    from woori.publications import ManualLiveRequestInput
    payload = {"content_version_id": uuid4(), "blog_id": uuid4(),
        "expected_title_sha256": "a"*64, "expected_body_sha256": "b"*64, "expected_html_sha256": "c"*64,
        "actor_label": "admin", "reason": "explicit review", "reviewed_exact_content": True,
        "assertions_safe_to_publish": True, "rights_privacy_harm_checked": True,
        "idempotency_key": "manual-explicit-mode-123", "publication_mode": mode,
        "confirmation": "SAVE THIS EXACT MANUSCRIPT AS DRAFT" if mode == "draft" else "PUBLISH THIS EXACT MANUSCRIPT PUBLICLY"}
    assert ManualLiveRequestInput.model_validate(payload).publication_mode == mode
    with pytest.raises(ValidationError):
        ManualLiveRequestInput.model_validate({**payload, "confirmation": "yes"})


def test_google_403_persists_stop_and_prevents_another_post(monkeypatch):
    calls = []
    with connection() as conn:
        @contextmanager
        def shared():
            with conn.transaction():
                yield conn
        monkeypatch.setattr(blogger_writes, "connection", shared)
        monkeypatch.setattr(publication_operation, "connection", shared)
        monkeypatch.setattr(blogger_writes.google_oauth, "access_token", lambda _: "mock-only")
        original = publication_operation.blogger_writes_allowed
        monkeypatch.setattr(publication_operation, "blogger_writes_allowed", lambda: True)
        def handler(request):
            calls.append(request.method)
            return httpx.Response(403, json={"error":{"errors":[{"reason":"forbidden"}]}})
        monkeypatch.setattr(external_policy, "client", lambda *args, **kwargs: httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(GoogleFailure):
            blogger_writes._live_response(connection_id=uuid4(), operation="blogger_draft_create", method="POST", path="/blogs/123/posts")
        row = conn.execute("SELECT emergency_stopped,blogger_api_restricted FROM publication_mode_settings WHERE scope_type='global'").fetchone()
        assert row['emergency_stopped'] and row['blogger_api_restricted']
        monkeypatch.setattr(publication_operation, "blogger_writes_allowed", original)
        with pytest.raises(GoogleFailure, match="authoring_only"):
            blogger_writes._live_response(connection_id=uuid4(), operation="blogger_draft_create", method="POST", path="/blogs/123/posts")
        assert calls == ['POST']  # Mock only; no second POST or real Google request.
