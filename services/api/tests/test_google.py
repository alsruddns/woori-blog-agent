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
from psycopg.types.json import Jsonb
from woori import blogger_drafts as drafts
from woori import blogger_service as service
from woori import google_oauth as oauth
from woori.blogger_writes import BloggerWriter
from woori.config import settings
from woori.db import connection
from woori.google_http import READ_SCOPE, WRITE_SCOPE, BloggerReader, GoogleFailure, classify
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
                "blogger_drafts",
                "blogger_writes",
                "blogger_routes",
                "multilingual",
                "main",
            ]:
                monkeypatch.setattr("woori." + name + ".connection", shared)
            yield conn
    finally:
        settings.cache_clear()


def google_mock(
    monkeypatch: pytest.MonkeyPatch, token_scope: str = READ_SCOPE
) -> list[httpx.Request]:
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
                    "scope": token_scope,
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


def test_write_oauth_is_separate_scope_and_keeps_existing_read_connection(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    old_id, _, _ = authorize()
    blog_id = sandbox.execute(
        "SELECT id FROM blogger_blogs WHERE language_code='ko' ORDER BY url LIMIT 1"
    ).fetchone()["id"]
    sandbox.execute(
        "UPDATE blogger_blogs SET oauth_connection_id=%s WHERE id=%s", (old_id, blog_id)
    )

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "writer-secret-access",
                    "refresh_token": "writer-secret-refresh",
                    "expires_in": 3600,
                    "scope": WRITE_SCOPE,
                },
            )
        return httpx.Response(200)

    monkeypatch.setattr(
        oauth, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    binding = "writer-binding-" + uuid.uuid4().hex
    flow = oauth.start(binding, "ignored label", permission="write")
    params = parse_qs(urlsplit(flow["authorization_url"]).query)
    assert params["scope"] == [WRITE_SCOPE]
    assert params["prompt"] == ["consent"]
    assert params["access_type"] == ["offline"]

    state = params["state"][0]
    writer_id = oauth.callback(state, binding, "writer-code")
    writer = sandbox.execute(
        "SELECT status,scopes,access_ciphertext,refresh_ciphertext FROM google_connections WHERE id=%s",
        (writer_id,),
    ).fetchone()
    old = sandbox.execute(
        "SELECT status,scopes,access_ciphertext FROM google_connections WHERE id=%s", (old_id,)
    ).fetchone()
    assert writer["status"] == "connected" and writer["scopes"] == [WRITE_SCOPE]
    assert "writer-secret-access" not in writer["access_ciphertext"]
    assert "writer-secret-refresh" not in writer["refresh_ciphertext"]
    assert old["status"] == "connected" and old["scopes"] == [READ_SCOPE]
    assert (
        sandbox.execute(
            "SELECT oauth_connection_id FROM blogger_blogs WHERE id=%s", (blog_id,)
        ).fetchone()["oauth_connection_id"]
        == old_id
    )
    assert oauth.access_token(writer_id, force=True) == "writer-secret-access"
    refresh = [request for request in calls if request.url.path == "/token"][-1]
    assert b"grant_type=refresh_token" in refresh.content


def connected_write_oauth(monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    google_mock(monkeypatch, token_scope=WRITE_SCOPE)
    binding = "shared-writer-" + uuid.uuid4().hex
    flow = oauth.start(binding, "shared writer", permission="write")
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    return oauth.callback(state, binding, "shared-writer-code")


def allow_blogger_cost_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service.external_policy,
        "status",
        lambda: {
            "providers": [
                {
                    "name": "google_blogger_read",
                    "calls_allowed": True,
                    "block_reason": None,
                }
            ]
        },
    )


def test_live_draft_preview_is_exact_single_use_and_never_calls_google(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    writer_id = connected_write_oauth(monkeypatch)
    calls = google_mock(monkeypatch, token_scope=WRITE_SCOPE)
    allow_blogger_cost_review(monkeypatch)
    blogs = sandbox.execute(
        "SELECT id,language_code,url FROM blogger_blogs WHERE active ORDER BY language_code"
    ).fetchall()
    snapshots = []
    for blog in blogs:
        blog_id = drafts.TEST_BLOG_IDS[blog["language_code"]]
        sandbox.execute("UPDATE blogger_blogs SET blog_id=%s WHERE id=%s", (blog_id, blog["id"]))
        snapshots.append(
            {
                "blog_record_id": str(blog["id"]),
                "language_code": blog["language_code"],
                "url": blog["url"],
                "blog_id": blog_id,
                "registered_blog_id": blog_id,
                "previous_connection_id": None,
            }
        )
    sandbox.execute(
        """INSERT INTO audit_events(event_type,payload) VALUES
        ('blogger.common_connection.verified',%s)""",
        (
            Jsonb(
                {
                    "connection_id": str(writer_id),
                    "verified_blog_count": len(blogs),
                    "blogs": snapshots,
                }
            ),
        ),
    )
    ko = next(blog for blog in blogs if blog["language_code"] == "ko")
    title, content = drafts.TEST_COPY["ko"]
    first = drafts.preview(ko["id"], writer_id, title, content)
    second = drafts.preview(ko["id"], writer_id, title, content)
    assert first["preview_id"] == second["preview_id"]
    assert first["blog_id"] == drafts.TEST_BLOG_IDS["ko"]
    assert first["is_draft"] is True and first["external_call_made"] is False
    assert not [request for request in calls if request.url.host == "www.googleapis.com"]
    assert (
        sandbox.execute(
            "SELECT count(*) AS n FROM blogger_write_operations WHERE idempotency_key LIKE 'live-draft:%'"
        ).fetchone()["n"]
        == 1
    )
    with pytest.raises(GoogleFailure, match="draft_target_or_test_copy_not_allowlisted"):
        drafts.preview(ko["id"], writer_id, "changed", "not allowlisted")


def test_common_connection_cost_gate_keeps_all_existing_mappings(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    writer_id = connected_write_oauth(monkeypatch)
    before = sandbox.execute(
        "SELECT id,oauth_connection_id FROM blogger_blogs ORDER BY id"
    ).fetchall()
    calls: list[httpx.Request] = []

    def no_network(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("cost-blocked common connection must not call Google")

    monkeypatch.setattr(
        service,
        "client",
        lambda: httpx.Client(transport=httpx.MockTransport(no_network)),
    )
    with pytest.raises(GoogleFailure, match="manual_zero_cost_review_required"):
        service.verify_common_connection(writer_id)
    after = sandbox.execute(
        "SELECT id,oauth_connection_id FROM blogger_blogs ORDER BY id"
    ).fetchall()
    assert after == before
    assert calls == []
    assert (
        sandbox.execute(
            "SELECT count(*) AS n FROM audit_events WHERE event_type='blogger.common_connection.verified'"
        ).fetchone()["n"]
        == 0
    )


def test_common_connection_requires_fresh_read_proof_and_explicit_approval(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    read_id, _, _ = authorize()
    blogs = sandbox.execute(
        "SELECT id,language_code,url,blog_id FROM blogger_blogs WHERE active ORDER BY language_code,url"
    ).fetchall()
    sandbox.execute("UPDATE blogger_blogs SET oauth_connection_id=%s WHERE active", (read_id,))
    writer_id = connected_write_oauth(monkeypatch)
    allow_blogger_cost_review(monkeypatch)
    calls: list[httpx.Request] = []
    entries = [
        {
            "id": str(blog["blog_id"] or 9000000000000000000 + index),
            "url": blog["url"],
            "name": f"{blog['language_code']} test blog",
        }
        for index, blog in enumerate(blogs)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path.endswith("/users/self/blogs")
        return httpx.Response(200, json={"items": entries})

    monkeypatch.setattr(
        service, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    verified = service.verify_common_connection(writer_id)
    assert verified["verified_blog_count"] == len(blogs)
    assert verified["identity_verified"] is False and verified["writes_enabled"] is False
    assert len(calls) == 1
    assert sandbox.execute(
        "SELECT count(*) AS n FROM blogger_blogs WHERE oauth_connection_id=%s", (read_id,)
    ).fetchone()["n"] == len(blogs)

    with pytest.raises(GoogleFailure, match="explicit_common_connection_approval_required"):
        service.assign_common_connection(writer_id, uuid.UUID(verified["verification_id"]), "yes")
    assigned = service.assign_common_connection(
        writer_id,
        uuid.UUID(verified["verification_id"]),
        service.COMMON_CONNECTION_APPROVAL,
    )
    assert assigned["assigned"] is True
    assert assigned["blog_count"] == len(blogs)
    assert assigned["publish_ready"] is False and assigned["writes_enabled"] is False
    assert sandbox.execute(
        "SELECT count(*) AS n FROM blogger_blogs WHERE oauth_connection_id=%s", (writer_id,)
    ).fetchone()["n"] == len(blogs)
    assert (
        sandbox.execute("SELECT status FROM google_connections WHERE id=%s", (read_id,)).fetchone()[
            "status"
        ]
        == "connected"
    )
    assert (
        sandbox.execute(
            "SELECT count(*) AS n FROM audit_events WHERE event_type='blogger.common_connection.assigned'"
        ).fetchone()["n"]
        == 1
    )
    audit_payloads = str(
        sandbox.execute(
            "SELECT payload FROM audit_events WHERE event_type LIKE 'blogger.common_connection.%'"
        ).fetchall()
    )
    assert "secret-access" not in audit_payloads
    assert "secret-refresh" not in audit_payloads


def test_existing_connected_write_oauth_prevents_duplicate_oauth_creation(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    writer_id = connected_write_oauth(monkeypatch)
    before = sandbox.execute("SELECT count(*) AS n FROM google_connections").fetchone()["n"]
    with pytest.raises(GoogleFailure, match="existing_write_connection_available"):
        oauth.start("another-writer-" + uuid.uuid4().hex, "duplicate", permission="write")
    assert sandbox.execute("SELECT count(*) AS n FROM google_connections").fetchone()["n"] == before
    assert (
        sandbox.execute(
            "SELECT status FROM google_connections WHERE id=%s", (writer_id,)
        ).fetchone()["status"]
        == "connected"
    )


def test_pending_write_consent_prevents_parallel_oauth_connection_creation(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    google_mock(monkeypatch)
    flow = oauth.start("pending-writer-" + uuid.uuid4().hex, "pending writer", permission="write")
    before = sandbox.execute("SELECT count(*) AS n FROM google_connections").fetchone()["n"]
    with pytest.raises(GoogleFailure, match="existing_write_connection_available"):
        oauth.start("parallel-writer-" + uuid.uuid4().hex, "parallel", permission="write")
    assert sandbox.execute("SELECT count(*) AS n FROM google_connections").fetchone()["n"] == before
    assert flow["connection_id"]


def test_api_exposes_distinct_read_and_write_consent_scopes(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = google_mock(monkeypatch)
    headers = {"Authorization": "Bearer " + settings().admin_token}
    with TestClient(app) as api:
        read = api.post(
            "/admin/blogger/oauth/start",
            headers=headers,
            json={"binding": "read-binding-" + uuid.uuid4().hex, "permission": "read"},
        )
        write = api.post(
            "/admin/blogger/oauth/start",
            headers=headers,
            json={"binding": "write-binding-" + uuid.uuid4().hex, "permission": "write"},
        )
        assert read.status_code == write.status_code == 200
        assert parse_qs(urlsplit(read.json()["authorization_url"]).query)["scope"] == [READ_SCOPE]
        assert parse_qs(urlsplit(write.json()["authorization_url"]).query)["scope"] == [WRITE_SCOPE]
        assert read.json()["authorization_url"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth?"
        )
        assert write.json()["authorization_url"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth?"
        )
    assert not calls


@pytest.mark.parametrize("failure", ["wrong_scope", "denied"])
def test_failed_write_oauth_preserves_existing_read_connection(
    sandbox: psycopg.Connection[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    google_mock(monkeypatch)
    old_id, _, _ = authorize()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "unexpected-scope-access",
                "refresh_token": "unexpected-scope-refresh",
                "expires_in": 3600,
                "scope": READ_SCOPE,
            },
        )

    monkeypatch.setattr(
        oauth, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    binding = "writer-binding-" + uuid.uuid4().hex
    flow = oauth.start(binding, "writer", permission="write")
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    with pytest.raises(GoogleFailure):
        if failure == "denied":
            oauth.callback(state, binding, "", denied=True)
        else:
            oauth.callback(state, binding, "wrong-scope-code")
    old = sandbox.execute(
        "SELECT status,scopes,access_ciphertext,refresh_ciphertext FROM google_connections WHERE id=%s",
        (old_id,),
    ).fetchone()
    assert old["status"] == "connected" and old["scopes"] == [READ_SCOPE]
    assert old["access_ciphertext"] and old["refresh_ciphertext"]
    pending = sandbox.execute(
        "SELECT status,access_ciphertext,refresh_ciphertext FROM google_connections WHERE id=%s",
        (flow["connection_id"],),
    ).fetchone()
    assert pending["status"] == "error"
    assert pending["access_ciphertext"] is None and pending["refresh_ciphertext"] is None


def test_write_oauth_refresh_keeps_old_refresh_token_when_google_omits_rotation(
    sandbox: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if b"grant_type=authorization_code" in request.content:
            return httpx.Response(
                200,
                json={
                    "access_token": "writer-access-initial",
                    "refresh_token": "writer-refresh-stable",
                    "expires_in": 3600,
                    "scope": WRITE_SCOPE,
                },
            )
        return httpx.Response(
            200,
            json={"access_token": "writer-access-rotated", "expires_in": 3600},
        )

    monkeypatch.setattr(
        oauth, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    binding = "writer-binding-" + uuid.uuid4().hex
    flow = oauth.start(binding, "writer", permission="write")
    state = parse_qs(urlsplit(flow["authorization_url"]).query)["state"][0]
    connection_id = oauth.callback(state, binding, "code")
    row_before = sandbox.execute(
        "SELECT refresh_ciphertext FROM google_connections WHERE id=%s", (connection_id,)
    ).fetchone()
    assert oauth.access_token(connection_id, force=True) == "writer-access-rotated"
    row_after = sandbox.execute(
        "SELECT scopes,refresh_ciphertext FROM google_connections WHERE id=%s", (connection_id,)
    ).fetchone()
    assert row_after["scopes"] == [WRITE_SCOPE]
    assert row_after["refresh_ciphertext"] == row_before["refresh_ciphertext"]
    assert "writer-refresh-stable" not in row_after["refresh_ciphertext"]


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
        (403, "rateLimitExceeded", "free_quota_exceeded"),
        (429, "", "free_quota_exceeded"),
        (503, "", "unavailable"),
        (404, "", "not_found"),
    ],
)
def test_error_classification(status: int, reason: str, expected: str) -> None:
    assert (
        classify(httpx.Response(status, json={"error": {"errors": [{"reason": reason}]}}))
        == expected
    )


def test_bounded_read_stops_on_free_quota_limit() -> None:
    statuses = iter([503, 429, 200])
    attempts = []
    pauses = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={"id": "1001"}, headers={"Retry-After": "999"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        reader = BloggerReader(
            transport, lambda: "never-logged", lambda *args: attempts.append(args), pauses.append
        )
        with pytest.raises(GoogleFailure, match="free_quota_exceeded"):
            reader.blog("1001")
    assert len([a for a in attempts if a[2] == "requested"]) == 2
    assert len(pauses) == 1 and max(pauses) <= 5


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
