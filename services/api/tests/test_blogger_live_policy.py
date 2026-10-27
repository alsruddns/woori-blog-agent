from datetime import UTC, datetime
from typing import Self
from uuid import UUID

import httpx
import pytest
from woori import blogger_drafts, external_policy


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
        blogger_drafts.oauth,
        "access_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no token or POST")),
    )

    with pytest.raises(blogger_drafts.GoogleFailure, match="matching_remote_test_draft_exists"):
        blogger_drafts.confirm(preview_id, blogger_drafts.CONFIRMATION_PHRASE)

    joined = " ".join(query for query, _ in executed)
    assert "status='duplicate_blocked'" in joined
    assert "blogger.draft.duplicate_blocked" in joined
    assert "blogger.draft.requested" not in joined
