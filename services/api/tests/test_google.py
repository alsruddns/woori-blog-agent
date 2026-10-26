import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from woori import blogger_service as service
from woori import google_oauth as oauth
from woori.blogger_writes import BloggerWriter
from woori.config import settings
from woori.db import connection
from woori.google_http import READ_SCOPE, BloggerReader, GoogleFailure, classify
from woori.main import app


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "unit-test-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "unit-test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings.cache_clear()
    try:
        with connection() as conn, conn.transaction(force_rollback=True):

            @contextmanager
            def shared() -> Iterator[psycopg.Connection[dict[str, Any]]]:
                with conn.transaction():
                    yield conn

            for name in [
                "google_oauth",
                "blogger_service",
                "blogger_writes",
                "blogger_routes",
                "multilingual",
                "main",
            ]:
                monkeypatch.setattr("woori." + name + ".connection", shared)
            yield conn
    finally:
        settings.cache_clear()


def google_mock(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "secret-access",
                    "refresh_token": "secret-refresh",
                    "expires_in": 3600,
                    "scope": READ_SCOPE,
                },
            )
        if request.url.path == "/revoke":
            return httpx.Response(200)
        if request.url.path.endswith("/blogs/byurl"):
            return httpx.Response(200, json={"id": "1001", "url": request.url.params["url"]})
        if request.url.path.endswith("/posts"):
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "2001", "title": "Mock post", "status": "LIVE"}],
                    "nextPageToken": "next",
                },
            )
        if request.url.path.endswith("/posts/2001"):
            return httpx.Response(
                200, json={"id": "2001", "title": "Mock post", "content": "<p>Safe as text</p>"}
            )
        return httpx.Response(
            200, json={"id": "1001", "name": "Mock blog", "posts": {"totalItems": 1}}
        )

    factory = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(oauth, "client", factory)
    monkeypatch.setattr(service, "client", factory)
    return calls


def authorize() -> tuple[uuid.UUID, str, str]:
    binding = "browser-binding-" + uuid.uuid4().hex
    flow = oauth.start(binding, "Unit test")
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    connection_id = oauth.callback(state, binding, "fake-authorization-code")
    return connection_id, state, binding


def test_oauth_state_encryption_refresh_and_disconnect(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = google_mock(monkeypatch)
    binding = "browser-" + uuid.uuid4().hex
    flow = oauth.start(binding, "Private test")
    params = parse_qs(urlsplit(flow["authorization_url"]).query)
    state = params["state"][0]
    assert params["scope"] == [READ_SCOPE]
    assert params["code_challenge_method"] == ["S256"]
    stored = sandbox.execute(
        "SELECT * FROM google_oauth_states WHERE state_hash=%s",
        (hashlib.sha256(state.encode()).hexdigest(),),
    ).fetchone()
    assert stored["verifier_ciphertext"] != oauth.decrypt(stored["verifier_ciphertext"])
    with pytest.raises(GoogleFailure, match="invalid_oauth_state"):
        oauth.callback(state, "incorrect-binding", "code")
    connection_id = oauth.callback(state, binding, "fake-code")
    assert oauth.access_token(connection_id) == "secret-access"
    row = sandbox.execute(
        "SELECT * FROM google_connections WHERE id=%s", (connection_id,)
    ).fetchone()
    assert "secret-access" not in row["access_ciphertext"]
    assert "secret-refresh" not in row["refresh_ciphertext"]
    with pytest.raises(GoogleFailure, match="invalid_oauth_state"):
        oauth.callback(state, binding, "replay")
    sandbox.execute(
        "UPDATE google_connections SET expires_at=now()-interval '1 minute' WHERE id=%s",
        (connection_id,),
    )
    assert oauth.access_token(connection_id) == "secret-access"
    assert any(b"grant_type=refresh_token" in r.content for r in calls)
    result = oauth.disconnect(connection_id)
    assert result == {"disconnected": True, "remote_revoked": True}
    assert sandbox.execute(
        "SELECT access_ciphertext,refresh_ciphertext FROM google_connections WHERE id=%s",
        (connection_id,),
    ).fetchone() == {"access_ciphertext": None, "refresh_ciphertext": None}
    payloads = str(
        sandbox.execute(
            "SELECT payload FROM audit_events WHERE event_type LIKE 'oauth.%'"
        ).fetchall()
    )
    assert (
        "secret-access" not in payloads
        and "secret-refresh" not in payloads
        and "fake-code" not in payloads
    )


def test_oauth_denied_expired_scope_and_revocation(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    for expired in [False, True]:
        binding = "binding-" + uuid.uuid4().hex
        flow = oauth.start(binding, "Test")
        state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
        if expired:
            sandbox.execute(
                "UPDATE google_oauth_states SET expires_at=now()-interval '1 second' WHERE state_hash=%s",
                (oauth.digest(state),),
            )
        with pytest.raises(GoogleFailure):
            oauth.callback(state, binding, "", True)
    connection_id, _, _ = authorize()
    monkeypatch.setattr(
        oauth,
        "client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400, json={"error": "invalid_grant", "error_description": "do-not-log-this"}
                )
            )
        ),
    )
    with pytest.raises(GoogleFailure, match="revoked"):
        oauth.access_token(connection_id, force=True)
    row = sandbox.execute(
        "SELECT status,refresh_ciphertext FROM google_connections WHERE id=%s", (connection_id,)
    ).fetchone()
    assert row["status"] == "revoked" and row["refresh_ciphertext"] is None
    assert "do-not-log-this" not in str(
        sandbox.execute("SELECT payload FROM audit_events").fetchall()
    )
    assert oauth.disconnect(connection_id)["disconnected"]


def test_real_protocol_reads_and_dynamic_configuration(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = google_mock(monkeypatch)
    connection_id, _, _ = authorize()
    headers = {"Authorization": "Bearer " + settings().admin_token}
    code = "fr-x-" + uuid.uuid4().hex[:8]
    with TestClient(app) as api:
        assert api.get("/admin/blogger/status").status_code == 401
        assert (
            api.post(
                "/admin/config/languages",
                headers=headers,
                json={"code": code, "display_name": "French test"},
            ).status_code
            == 201
        )
        blog = api.post(
            "/admin/config/blogs",
            headers=headers,
            json={
                "language_code": code,
                "url": "https://test-" + uuid.uuid4().hex + ".blogspot.com",
                "display_name": "Test",
            },
        ).json()
        connected = api.post(
            "/admin/blogger/blogs/" + blog["id"] + "/connect",
            headers=headers,
            json={"connection_id": str(connection_id)},
        )
        assert connected.status_code == 200, connected.text
        assert connected.json()["blog_id"] == "1001"
        base = "/admin/blogger/blogs/" + blog["id"]
        assert api.get(base + "/posts", headers=headers).json()["items"][0]["id"] == "2001"
        assert api.get(base + "/posts/2001", headers=headers).json()["title"] == "Mock post"
        assert api.post(base + "/test", headers=headers).json()["tested"]
        state = api.get("/admin/blogger/status", headers=headers).json()
        assert any(x["blog_id"] == blog["id"] for x in state["calls"])
        assert "access_ciphertext" not in str(state["connections"])
        n = len(calls)
        assert (
            api.put(
                "/admin/blogger/limits/" + code,
                headers=headers,
                json={"read_enabled": False, "requests_per_minute": 1, "max_page_size": 5},
            ).status_code
            == 200
        )
        assert (
            api.get(base + "/posts", headers=headers).json()["error"] == "language_or_blog_disabled"
        )
        assert len(calls) == n
        assert (
            api.put(
                "/admin/blogger/limits/" + code,
                headers=headers,
                json={"read_enabled": True, "requests_per_minute": 1, "max_page_size": 5},
            ).status_code
            == 200
        )
        assert api.get(base + "/posts", headers=headers).status_code == 429
        assert len(calls) == n
        assert (
            api.put(
                "/admin/blogger/limits/" + code,
                headers=headers,
                json={
                    "read_enabled": True,
                    "requests_per_minute": 1,
                    "max_page_size": 5,
                    "publishing_enabled": True,
                },
            ).status_code
            == 422
        )
        assert api.post(base + "/disconnect", headers=headers).json()["disconnected"]
        saved = sandbox.execute(
            "SELECT blog_id,oauth_connection_id FROM blogger_blogs WHERE id=%s", (blog["id"],)
        ).fetchone()
        assert saved["blog_id"] == "1001" and saved["oauth_connection_id"] is None


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (401, "", "unauthorized"),
        (403, "forbidden", "permission_denied"),
        (403, "rateLimitExceeded", "rate_limit"),
        (429, "", "rate_limit"),
        (503, "", "unavailable"),
        (404, "", "not_found"),
    ],
)
def test_error_classification(status: int, reason: str, expected: str) -> None:
    assert (
        classify(httpx.Response(status, json={"error": {"errors": [{"reason": reason}]}}))
        == expected
    )


def test_bounded_read_retries() -> None:
    statuses = iter([503, 429, 200])
    attempts = []
    pauses = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={"id": "1001"}, headers={"Retry-After": "999"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        reader = BloggerReader(
            transport, lambda: "never-logged", lambda *args: attempts.append(args), pauses.append
        )
        assert reader.blog("1001")["id"] == "1001"
    assert len([a for a in attempts if a[2] == "requested"]) == 3
    assert len(pauses) == 2 and max(pauses) <= 5


def test_mock_writes_idempotency_and_ambiguous_failure(
    sandbox: psycopg.Connection[dict[str, Any]],
) -> None:
    with pytest.raises(GoogleFailure, match="production_writes_disabled"):
        BloggerWriter()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return (
            httpx.Response(204)
            if request.method == "DELETE"
            else httpx.Response(200, json={"id": "2001", "status": "MOCK"})
        )

    writer = BloggerWriter(httpx.MockTransport(handler))
    key = uuid.uuid4().hex
    first = writer.create_draft(key, "1001", "Title", "Body")
    assert writer.create_draft(key, "1001", "Title", "Body") == first
    assert len(calls) == 1 and calls[0].url.params["isDraft"] == "true"
    with pytest.raises(GoogleFailure, match="duplicate_or_uncertain"):
        writer.create_draft(key, "1001", "Changed title", "Body")
    writer.publish(uuid.uuid4().hex, "1001", "2001")
    writer.schedule(
        uuid.uuid4().hex, "1001", "2001", (datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    assert "publishDate" in calls[-1].url.params
    writer.update(uuid.uuid4().hex, "1001", "2001", "New title", "New body")
    writer.delete(uuid.uuid4().hex, "1001", "2001")
    assert calls[-2].method == "PATCH" and calls[-1].method == "DELETE"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-response-not-logged")

    writer = BloggerWriter(httpx.MockTransport(timeout))
    key = uuid.uuid4().hex
    with pytest.raises(GoogleFailure, match="uncertain_write"):
        writer.create_draft(key, "1001", "Title", "Body")
    with pytest.raises(GoogleFailure, match="duplicate_or_uncertain"):
        writer.create_draft(key, "1001", "Title", "Body")


def test_local_content_is_versioned_not_published(
    sandbox: psycopg.Connection[dict[str, Any]],
) -> None:
    headers = {"Authorization": "Bearer " + settings().admin_token}
    with TestClient(app) as api:
        first = api.post(
            "/admin/blogger/content",
            headers=headers,
            json={"language_code": "ko", "title": "Local only", "body": "Original"},
        )
        assert first.status_code == 201, first.text
        second = api.post(
            "/admin/blogger/content",
            headers=headers,
            json={
                "language_code": "ko",
                "group_id": first.json()["group_id"],
                "title": "Revision",
                "body": "Revised",
            },
        )
        assert second.status_code == 201 and second.json()["version"] == 2
        assert (
            sandbox.execute(
                "SELECT body FROM content_versions WHERE id=%s", (first.json()["id"],)
            ).fetchone()["body"]
            == "Original"
        )
        assert (
            api.get("/admin/blogger/content?language_code=ko", headers=headers).status_code == 200
        )


@pytest.mark.parametrize("failure", ["missing_refresh", "excess_scope", "invalid_json"])
def test_oauth_token_failures_are_sanitized(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "invalid_json":
            return httpx.Response(200, text="secret-invalid-body")
        body = {"access_token": "secret-test-access", "expires_in": 3600, "scope": READ_SCOPE}
        if failure == "excess_scope":
            body["scope"] = "https://www.googleapis.com/auth/blogger"
            body["refresh_token"] = "secret-test-refresh"
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        oauth, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    binding = "binding-" + uuid.uuid4().hex
    flow = oauth.start(binding, "Rejected token")
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    with pytest.raises(GoogleFailure):
        oauth.callback(state, binding, "secret-code")
    row = sandbox.execute(
        "SELECT status,access_ciphertext FROM google_connections WHERE id=%s",
        (flow["connection_id"],),
    ).fetchone()
    assert row["status"] == "error" and row["access_ciphertext"] is None
    assert "secret-code" not in str(sandbox.execute("SELECT payload FROM audit_events").fetchall())


def test_pending_disconnect_and_wrong_encryption_key(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    binding = "binding-" + uuid.uuid4().hex
    flow = oauth.start(binding, "Cancelled")
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    oauth.disconnect(uuid.UUID(flow["connection_id"]))
    with pytest.raises(GoogleFailure, match="invalid_oauth_state"):
        oauth.callback(state, binding, "late-code")
    connection_id, _, _ = authorize()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings.cache_clear()
    with pytest.raises(GoogleFailure, match="token_decryption_failed"):
        oauth.access_token(connection_id)
    assert (
        sandbox.execute(
            "SELECT status FROM google_connections WHERE id=%s", (connection_id,)
        ).fetchone()["status"]
        == "error"
    )


def test_unrecoverable_read_network_error_is_bounded() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("do-not-log-transport-details")

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        reader = BloggerReader(
            transport, lambda: "token", lambda *a: attempts.append(a), lambda _: None
        )
        with pytest.raises(GoogleFailure, match="network"):
            reader.blog("1001")
    assert len([a for a in attempts if a[2] == "requested"]) == 3


def test_live_pagination_regression_and_account_path() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/users/self/blogs"):
            return httpx.Response(200, json={"items": [{"id": "1001"}]})
        if "pageToken" not in request.url.params:
            return httpx.Response(200, json={"items": [{"id": "2001"}], "nextPageToken": "next"})
        assert request.url.params["pageToken"] == "next"
        return httpx.Response(200, json={"items": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        reader = BloggerReader(transport, lambda: "test-token", lambda *a: None)
        assert reader.account_blogs()["items"][0]["id"] == "1001"
        first = reader.posts("1001")
        assert reader.posts("1001", page_token=first["nextPageToken"])["items"] == []
        with pytest.raises(GoogleFailure, match="invalid_path"):
            reader.get("invalid", "/users/another/blogs")
    assert len(calls) == 3


def test_account_scoped_audit(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    connection_id, _, _ = authorize()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        service, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    headers = {"Authorization": "Bearer " + settings().admin_token}
    with TestClient(app) as api:
        assert api.get(f"/admin/blogger/oauth/{connection_id}/blogs").status_code == 401
        assert api.get(f"/admin/blogger/oauth/{connection_id}/blogs", headers=headers).json() == {}
    row = sandbox.execute(
        "SELECT * FROM blogger_api_calls WHERE connection_id=%s AND operation='list_account_blogs' AND status='succeeded'",
        (connection_id,),
    ).fetchone()
    assert row and row["blog_id"] is None and row["language_code"] is None
    assert row["http_status"] == 200
    assert len(calls) == 1


def test_unauthorized_read_refreshes_once(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    connection_id, _, _ = authorize()
    code = "de-x-" + uuid.uuid4().hex[:8]
    headers = {"Authorization": "Bearer " + settings().admin_token}
    with TestClient(app) as api:
        api.post(
            "/admin/config/languages",
            headers=headers,
            json={"code": code, "display_name": "Test German"},
        )
        blog = api.post(
            "/admin/config/blogs",
            headers=headers,
            json={
                "language_code": code,
                "display_name": "Test",
                "url": "https://test-" + uuid.uuid4().hex + ".blogspot.com",
            },
        ).json()
        service.connect_blog(uuid.UUID(blog["id"]), connection_id)
    statuses = iter([401, 200])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(next(statuses), json={})

    monkeypatch.setattr(
        service, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert service.posts(uuid.UUID(blog["id"]))["items"] == []
    assert len(calls) == 2
    attempts = sandbox.execute(
        "SELECT attempt FROM blogger_api_calls WHERE blog_id=%s AND status='requested' ORDER BY id DESC LIMIT 2",
        (blog["id"],),
    ).fetchall()
    assert [a["attempt"] for a in attempts] == [2, 1]
