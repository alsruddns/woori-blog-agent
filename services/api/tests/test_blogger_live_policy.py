import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

import httpx
import pytest
from woori import blogger_drafts, external_policy
from woori.google_http import GoogleFailure


def _request(method: str, path: str, params: dict[str, str] | None = None) -> httpx.Request:
    return httpx.Request(
        method,
        "https://www.googleapis.com/blogger/v3" + path,
        params=params,
    )


def test_blogger_gate_requires_owner_approval_but_does_not_change_other_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: None)
    blocked = next(
        item
        for item in external_policy.status()["providers"]
        if item["name"] == "google_blogger_read"
    )
    assert blocked["calls_allowed"] is False
    assert blocked["block_reason"] == "manual_zero_cost_review_required"
    assert external_policy.PROVIDERS["federal_reserve"]["zero_cost_reviewed"] is True


def test_scheduled_public_approval_is_scoped_and_does_not_enable_manual_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"scope": ["blogger_read"]})
    monkeypatch.setattr(external_policy, "_blogger_public_publish_approval", lambda: None)
    monkeypatch.setattr(
        external_policy, "_scheduled_publication_approval",
        lambda blog_id: {"scope": ["scheduled_publication"]} if blog_id == "blog-record-ko" else None,
    )

    assert not external_policy._blogger_operation_is_approved("blogger_public_publish")
    with external_policy.scheduled_publication_context("blog-record-ko"):
        assert external_policy._blogger_operation_is_approved("blogger_public_publish")
    with external_policy.scheduled_publication_context("different-blog"):
        assert not external_policy._blogger_operation_is_approved("blogger_public_publish")

    approval = {
        "created_at": datetime.now(UTC),
        "scope": sorted(external_policy.BLOGGER_APPROVAL_SCOPE),
    }
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: approval)
    allowed = next(
        item
        for item in external_policy.status()["providers"]
        if item["name"] == "google_blogger_read"
    )
    assert allowed["calls_allowed"] is True
    assert allowed["zero_cost_reviewed"] is True
    assert "private_draft_create" in allowed["approval_scope"]
    assert external_policy.PROVIDERS["federal_reserve"]["zero_cost_reviewed"] is True


@pytest.mark.parametrize(
    ("operation", "method", "path", "params"),
    [
        ("blogger_read", "GET", "/users/self/blogs", None),
        ("blogger_draft_create", "POST", "/blogs/123/posts", {"isDraft": "true"}),
        ("blogger_post_update", "PATCH", "/blogs/123/posts/456", None),
        ("blogger_post_update", "PUT", "/blogs/123/posts/456", None),
    ],
)
def test_approved_blogger_operations_are_narrowly_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    method: str,
    path: str,
    params: dict[str, str] | None,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        external_policy, "_blogger_operation_is_approved", lambda op: op == operation
    )
    external_policy._authorize("google_blogger_read", operation, _request(method, path, params))


def test_publish_route_allows_only_exact_blogger_draft_publish_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(external_policy, "_blogger_operation_is_approved", lambda op: op == "blogger_public_publish")
    external_policy._authorize(
        "google_blogger_read", "blogger_public_publish",
        _request("POST", "/blogs/123/posts/456/publish"),
    )
    with pytest.raises(external_policy.ExternalCallBlocked):
        external_policy._authorize(
            "google_blogger_read", "blogger_public_publish",
            _request("POST", "/blogs/123/posts/456/publish", {"publishDate": "later"}),
        )
    with pytest.raises(external_policy.ExternalCallBlocked):
        external_policy._authorize(
            "google_blogger_read", "blogger_public_publish",
            _request("DELETE", "/blogs/123/posts/456"),
        )


@pytest.mark.parametrize(
    ("operation", "method", "path", "params"),
    [
        ("blogger_draft_create", "POST", "/blogs/123/posts", None),
        ("blogger_draft_create", "POST", "/blogs/123/posts", {"isDraft": "false"}),
        ("blogger_draft_create", "POST", "/blogs/123/posts/456/publish", None),
        ("blogger_post_update", "DELETE", "/blogs/123/posts/456", None),
        ("blogger_post_update", "POST", "/blogs/123/posts/456/publish", None),
        ("blogger_read", "POST", "/blogs/123/posts", None),
    ],
)
def test_publish_delete_and_unapproved_blogger_shapes_stay_blocked(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    method: str,
    path: str,
    params: dict[str, str] | None,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(external_policy, "_blogger_operation_is_approved", lambda op: True)
    with pytest.raises(external_policy.ExternalCallBlocked):
        external_policy._authorize("google_blogger_read", operation, _request(method, path, params))


def test_public_publish_requires_separate_scope_not_in_existing_owner_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        external_policy,
        "_blogger_policy_approval",
        lambda: {"created_at": datetime.now(UTC), "scope": sorted(external_policy.BLOGGER_APPROVAL_SCOPE)},
    )
    assert external_policy._blogger_operation_is_approved("blogger_draft_create")
    assert not external_policy._blogger_operation_is_approved("blogger_public_publish")


def test_manual_public_publish_is_scoped_to_explicit_job_context_and_cost_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        external_policy,
        "_blogger_policy_approval",
        lambda: {"created_at": datetime.now(UTC), "scope": sorted(external_policy.BLOGGER_APPROVAL_SCOPE)},
    )
    monkeypatch.setattr(external_policy, "_blogger_public_publish_approval", lambda: None)
    assert not external_policy._blogger_operation_is_approved("blogger_public_publish")
    with external_policy.manual_publication_context(
        "job-1", "blog-1", "version-1", "a" * 64, "b" * 64, "c" * 64,
    ):
        assert external_policy._blogger_operation_is_approved("blogger_public_publish")
    assert not external_policy._blogger_operation_is_approved("blogger_public_publish")

    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: None)
    with external_policy.manual_publication_context(
        "job-1", "blog-1", "version-1", "a" * 64, "b" * 64, "c" * 64,
    ):
        assert not external_policy._blogger_operation_is_approved("blogger_public_publish")


def test_live_public_publish_gate_blocks_before_transport_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    from woori.blogger_writes import _live_response

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"id": "123"}, request=request)

    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        external_policy,
        "_blogger_policy_approval",
        lambda: {"created_at": datetime.now(UTC), "scope": sorted(external_policy.BLOGGER_APPROVAL_SCOPE)},
    )
    monkeypatch.setattr("woori.blogger_writes.google_oauth.access_token", lambda _id: "test-token")

    with pytest.raises(GoogleFailure, match="provider_cost_unverified"):
        _live_response(
            connection_id=UUID("00000000-0000-0000-0000-000000000001"),
            operation="blogger_public_publish",
            method="POST",
            path="/blogs/123/posts/456/publish",
            transport=httpx.MockTransport(handler),
        )
    assert called is False


@pytest.mark.parametrize(("readback_status", "verified"), [("DRAFT", True), ("LIVE", False)])
def test_live_draft_is_read_back_before_success_is_recorded(
    monkeypatch: pytest.MonkeyPatch, readback_status: str, verified: bool,
) -> None:
    from woori import blogger_writes

    blog_record_id = UUID("00000000-0000-0000-0000-000000000001")
    oauth_id = UUID("00000000-0000-0000-0000-000000000002")
    calls: list[tuple[str, str]] = []
    finish_calls: list[tuple[object, ...]] = []
    submitted: dict[str, str] = {}

    class FakeConnection:
        class Result:
            def __init__(self, row: dict[str, object]) -> None:
                self.row = row

            def fetchone(self) -> dict[str, object]:
                return self.row

        def execute(self, query: str, params: tuple[object, ...] = ()) -> Result:
            if "SELECT b.id,b.language_code" in query:
                return self.Result({
                    "id": blog_record_id, "language_code": "ko", "url": "https://trend-ko.blogspot.com/",
                    "blog_id": "123", "active": True, "oauth_connection_id": oauth_id,
                    "oauth_status": "connected", "scopes": [blogger_writes.WRITE_SCOPE],
                })
            if "INSERT INTO blogger_write_operations" in query:
                return self.Result({"idempotency_key": params[0]})
            if "UPDATE blogger_write_operations" in query:
                finish_calls.append(params)
            return self.Result({})

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(blogger_writes, "connection", fake_connection)
    monkeypatch.setattr(blogger_writes.google_oauth, "access_token", lambda _id: "test-token")
    monkeypatch.setattr(blogger_writes.external_policy, "billing_credential_names", list)
    monkeypatch.setattr(blogger_writes.external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(blogger_writes.external_policy, "_blogger_operation_is_approved", lambda _op: True)
    monkeypatch.setattr(blogger_writes.BloggerLivePublisher, "_account_write_guard",
                        staticmethod(lambda _target: nullcontext()))

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path.endswith("/blogs/123"):
            return httpx.Response(200, json={"id": "123", "url": "https://trend-ko.blogspot.com/"}, request=request)
        if request.method == "POST":
            submitted.update(json.loads(request.content))
            return httpx.Response(200, json={"id": "456", "blog": {"id": "123"}, "status": "DRAFT"}, request=request)
        return httpx.Response(200, json={"id": "456", "blog": {"id": "123"}, "status": readback_status, **submitted}, request=request)

    publisher = blogger_writes.BloggerLivePublisher(httpx.MockTransport(handler))
    if verified:
        result = publisher.create_draft(
            "draft-once", blog_record_id, "검증 초안", "<p>비공개 검증 초안</p>"
        )
        assert result["post_id"] == "456"
        assert result["live"] is True and result["simulation_only"] is False
        assert result["post_verified"] is True
        assert finish_calls[-1][0] == "succeeded"
    else:
        with pytest.raises(GoogleFailure, match="draft_readback_mismatch"):
            publisher.create_draft("draft-once", blog_record_id, "검증 초안", "<p>비공개 검증 초안</p>")
        assert finish_calls[-1][0] == "failed"
    assert [method for method, _ in calls] == ["GET", "POST", "GET"]
    assert calls[-1][1].endswith("/blogs/123/posts/456")


def test_live_publish_requires_remote_live_readback_and_uses_same_post(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import nullcontext

    from woori import blogger_writes

    blog_record_id = UUID("00000000-0000-0000-0000-000000000001")
    oauth_id = UUID("00000000-0000-0000-0000-000000000002")
    calls: list[tuple[str, str]] = []

    class Result:
        def __init__(self, value: dict[str, object] | None) -> None:
            self.value = value
        def fetchone(self) -> dict[str, object] | None:
            return self.value

    class FakeConnection:
        def execute(self, query: str, params: tuple[object, ...] = ()) -> Result:
            if "SELECT b.id,b.language_code" in query:
                return Result({"id": blog_record_id, "language_code": "ko", "url": "https://trend-ko.blogspot.com/",
                    "blog_id": "123", "active": True, "oauth_connection_id": oauth_id,
                    "oauth_status": "connected", "scopes": [blogger_writes.WRITE_SCOPE]})
            if "SELECT 1 FROM blogger_write_operations" in query:
                return Result({"verified": True})
            if "SELECT request_fingerprint,status,result" in query:
                return Result(None)
            if "INSERT INTO blogger_write_operations" in query:
                return Result({"idempotency_key": params[0]})
            return Result(None)

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(blogger_writes, "connection", fake_connection)
    monkeypatch.setattr(blogger_writes.google_oauth, "access_token", lambda _id: "test-token")
    monkeypatch.setattr(blogger_writes.external_policy, "billing_credential_names", list)
    monkeypatch.setattr(blogger_writes.external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(blogger_writes.external_policy, "_blogger_operation_is_approved", lambda _op: True)
    monkeypatch.setattr(blogger_writes.BloggerLivePublisher, "_account_write_guard",
                        staticmethod(lambda _target: nullcontext()))

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/blogs/123"):
            return httpx.Response(200, json={"id": "123", "url": "https://trend-ko.blogspot.com"}, request=request)
        if request.url.path.endswith("/posts/456/publish"):
            return httpx.Response(200, json={"status": "LIVE"}, request=request)
        if request.url.path.endswith("/posts/456") and len([c for c in calls if c[0] == "GET" and c[1].endswith("/posts/456")]) == 1:
            return httpx.Response(200, json={"id": "456", "blog": {"id": "123"}, "status": "DRAFT",
                "title": "검증 초안", "content": "<p>본문</p>"}, request=request)
        return httpx.Response(200, json={"id": "456", "blog": {"id": "123"}, "status": "LIVE",
            "title": "검증 초안", "content": "<p>본문</p>", "url": "https://trend-ko.blogspot.com/2026/10/test.html",
            "published": "2026-10-29T02:00:00Z"}, request=request)

    publisher = blogger_writes.BloggerLivePublisher(httpx.MockTransport(handler))
    result = publisher.publish_draft("publish-once", blog_record_id, "456", source_draft_key="draft-once")
    assert result["status"] == "LIVE" and result["readback_verified"] is True
    assert result["post_id"] == "456" and result["url"].endswith("test.html")
    assert [path for method, path in calls if method == "POST"] == ["/blogger/v3/blogs/123/posts/456/publish"]
    assert sum(method == "GET" and path.endswith("/posts/456") for method, path in calls) == 2


def test_policy_approval_requires_exact_scoped_append_only_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __init__(self, row: dict[str, object] | None) -> None:
            self.row = row

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object) -> "FakeConnection":
            return self

        def fetchone(self) -> dict[str, object] | None:
            return self.row

    approved = {
        "event_type": external_policy.BLOGGER_APPROVAL_EVENT,
        "payload": {
            "policy_version": 1,
            "actor": "project_owner_attestation_from_user_instruction",
            "evidence": "PROJECT_OWNER_CONFIRMS_BLOGGER_API_ZERO_COST",
            "approved_scope": sorted(external_policy.BLOGGER_APPROVAL_SCOPE),
        },
        "created_at": datetime.now(UTC),
    }
    # The lookup imports the DB context manager locally, so replace that module seam.
    from woori import db

    monkeypatch.setattr(db, "connection", lambda: FakeConnection(approved))
    assert external_policy._blogger_policy_approval() is not None
    revoked = {**approved, "event_type": external_policy.BLOGGER_REVOCATION_EVENT}
    monkeypatch.setattr(db, "connection", lambda: FakeConnection(revoked))
    assert external_policy._blogger_policy_approval() is None


def test_draft_confirmation_requires_exact_operator_phrase_before_database_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        external_policy,
        "status",
        lambda: (_ for _ in ()).throw(AssertionError("cost policy must not be consulted yet")),
    )
    with pytest.raises(
        blogger_drafts.GoogleFailure, match="explicit_private_draft_approval_required"
    ):
        blogger_drafts.confirm(UUID("00000000-0000-0000-0000-000000000001"), "yes")


def test_blogger_cost_gate_blocks_before_draft_confirm_database_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        external_policy,
        "status",
        lambda: {
            "providers": [
                {
                    "name": "google_blogger_read",
                    "calls_allowed": False,
                    "block_reason": "manual_zero_cost_review_required",
                }
            ]
        },
    )
    with pytest.raises(blogger_drafts.GoogleFailure, match="manual_zero_cost_review_required"):
        blogger_drafts.confirm(
            UUID("00000000-0000-0000-0000-000000000001"),
            blogger_drafts.CONFIRMATION_PHRASE,
        )


def test_duplicate_draft_title_is_detected_before_any_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = iter(
        [
            {"items": [], "nextPageToken": "page-2"},
            {"items": [{"id": "post-77", "title": "fixed test title"}]},
        ]
    )
    calls: list[tuple[str, int, str, str]] = []

    def fake_read(blog, connection_id, action):
        del action
        calls.append((blog["blog_id"], 50, "draft", str(connection_id)))
        return next(pages)

    monkeypatch.setattr(blogger_drafts.service, "read", fake_read)
    page_count, duplicate_id = blogger_drafts._find_existing_test_draft(
        {"blog_id": "123", "language_code": "ko"},
        UUID("00000000-0000-0000-0000-000000000002"),
        "fixed test title",
    )
    assert (page_count, duplicate_id) == (2, "post-77")
    assert len(calls) == 2


def test_duplicate_pagination_cycle_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"items": [], "nextPageToken": "same-token"}
    monkeypatch.setattr(blogger_drafts.service, "read", lambda *args: page)
    with pytest.raises(blogger_drafts.GoogleFailure, match="duplicate_check_pagination_limit"):
        blogger_drafts._find_existing_test_draft(
            {"blog_id": "123", "language_code": "ko"},
            UUID("00000000-0000-0000-0000-000000000003"),
            "fixed test title",
        )


def test_remote_duplicate_blocks_insert_and_commits_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    preview_id = UUID("00000000-0000-0000-0000-000000000004")
    connection_id = UUID("00000000-0000-0000-0000-000000000005")
    blog_id = UUID("00000000-0000-0000-0000-000000000006")
    result = {
        "preview_id": str(preview_id),
        "connection_id": str(connection_id),
        "blog_record_id": str(blog_id),
        "blog_id": "123",
        "language_code": "ko",
        "title": "fixed test title",
        "content": "fixed body",
        "payload_sha256": "fingerprint",
    }
    executed: list[tuple[str, object]] = []

    class FakeConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, params: object = None) -> "FakeConnection":
            executed.append((query, params))
            return self

        def fetchone(self) -> dict[str, object]:
            return {
                "idempotency_key": "live-draft:key",
                "request_fingerprint": "fingerprint",
                "status": "pending",
                "result": result,
            }

    monkeypatch.setattr(blogger_drafts, "connection", lambda: FakeConnection())
    monkeypatch.setattr(blogger_drafts, "_require_cost_approval", lambda: None)
    monkeypatch.setattr(
        blogger_drafts.service,
        "blog_record",
        lambda _blog_id: {"id": blog_id, "language_code": "ko"},
    )
    monkeypatch.setattr(blogger_drafts, "_verified_target", lambda *_args: None)
    monkeypatch.setattr(
        blogger_drafts,
        "_find_existing_test_draft",
        lambda *_args: (1, "remote-post-9"),
    )
    monkeypatch.setattr(
        blogger_drafts.service,
        "read",
        lambda *_args, **_kwargs: {"items": [{"id": "remote-post-9", "title": "fixed test title"}]},
    )

    with pytest.raises(blogger_drafts.GoogleFailure, match="matching_remote_test_draft_exists"):
        blogger_drafts.confirm(preview_id, blogger_drafts.CONFIRMATION_PHRASE)

    joined = " ".join(query for query, _ in executed)
    assert "SET status='failed'" in joined
    assert "blogger.draft.duplicate_blocked" in joined
    assert "blogger.draft.requested" not in joined


def test_worker_processes_confirmed_draft_through_live_adapter_and_records_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview_id = UUID("00000000-0000-0000-0000-000000000014")
    blog_record_id = UUID("00000000-0000-0000-0000-000000000015")
    connection_id = UUID("00000000-0000-0000-0000-000000000016")
    payload = {
        "preview_id": str(preview_id),
        "connection_id": str(connection_id),
        "blog_record_id": str(blog_record_id),
        "blog_id": "123",
        "language_code": "ko",
        "title": "Private worker test",
        "content": "Line one\n\n<script>plain text only</script>",
        "confirmation_recorded": True,
    }
    statements: list[tuple[str, object]] = []

    class FakeConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, params: object = None) -> "FakeConnection":
            statements.append((query, params))
            return self

        def fetchone(self) -> dict[str, object]:
            return {"idempotency_key": "live-draft:worker-test", "result": payload}

    class Publisher:
        def create_draft(self, key: str, blog_id: UUID, title: str, body_html: str) -> dict[str, object]:
            assert key == "live-draft:worker-test"
            assert blog_id == blog_record_id
            assert title == "Private worker test"
            assert body_html == "<p>Line one</p><p>&lt;script&gt;plain text only&lt;/script&gt;</p>"
            return {"post_id": "456", "blog_id": "123", "status": "DRAFT",
                    "http_status": 200, "post_verified": True}

    monkeypatch.setattr(blogger_drafts, "connection", lambda: FakeConnection())
    monkeypatch.setattr(blogger_drafts, "BloggerLivePublisher", Publisher)
    result = blogger_drafts.process_next_queued_draft()

    assert result == {
        "preview_id": str(preview_id), "status": "succeeded", "post_id": "456",
        "verification": {"checked": True, "is_draft": True,
                          "title_matches": True, "content_matches": True},
        "error_category": None,
    }
    joined = " ".join(query for query, _ in statements)
    assert "FOR UPDATE SKIP LOCKED" in joined
    assert "WHERE idempotency_key=%s AND status='uncertain'" in joined
    assert any(
        params and "blogger.draft.worker.completed" in params
        for query, params in statements
    )
