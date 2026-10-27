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
