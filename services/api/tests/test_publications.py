from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from woori.publications import (
    DisabledRealBloggerPublisher,
    FakeBloggerPublisher,
    PublicationError,
    ScheduleInput,
    _assess,
    sync_readonly,
    transition_allowed,
)


def test_publication_eligibility_fails_closed_even_for_machine_pass() -> None:
    row = {
        "language_active": True,
        "blog_active": True,
        "version_language": "en",
        "blog_language": "en",
        "blog_id_value": "123456789",
        "connection_verified_at": datetime.now(UTC),
        "test_publish_verified_at": datetime.now(UTC),
        "oauth_status": "connected",
        "policy_id": "policy",
        "policy_active": True,
        "auto_publish_allowed": False,
        "machine_passed": True,
        "human_review_required": True,
        "human_review_approved": False,
        "publish_ready": False,
    }
    result = _assess(row)
    assert result["state"] == "human_review_pending"
    assert "human_review_pending" in result["reasons"]
    assert "publish_ready_disabled" in result["reasons"]
    assert "production_writes_disabled" in result["reasons"]


def test_quality_failure_remains_held_and_not_eligible() -> None:
    row = {
        "language_active": True,
        "blog_active": True,
        "version_language": "ko",
        "blog_language": "ko",
        "blog_id_value": "123",
        "connection_verified_at": datetime.now(UTC),
        "test_publish_verified_at": datetime.now(UTC),
        "oauth_status": "connected",
        "policy_id": "policy",
        "policy_active": True,
        "auto_publish_allowed": False,
        "machine_passed": False,
        "human_review_required": True,
        "human_review_approved": False,
        "publish_ready": False,
    }
    assert _assess(row)["state"] == "quality_held"


def test_fake_publisher_is_network_free_and_fake_identifier_is_distinct() -> None:
    publisher = FakeBloggerPublisher()
    result = publisher.publish("success")
    assert result["outcome"] == "succeeded"
    assert result["simulation_only"] is True
    assert result["external_network_calls"] == 0
    assert result["real_blog_mutated"] is False
    assert str(result["fake_post_id"]).startswith("fake-post-")
    assert publisher.publish("timeout")["outcome"] == "failed"
    assert publisher.publish("uncertain")["outcome"] == "uncertain"
    with pytest.raises(PublicationError, match="invalid_mock_scenario"):
        publisher.publish("live")


def test_disabled_real_publisher_never_falls_back_to_network() -> None:
    with pytest.raises(PublicationError, match="production_writes_disabled"):
        DisabledRealBloggerPublisher().publish("123", {"title": "test"})


def test_publication_state_machine_rejects_skipped_review_and_terminal_changes() -> None:
    assert transition_allowed("human_review_pending", "human_review_approved")
    assert not transition_allowed("human_review_pending", "publication_queued")
    assert not transition_allowed("published", "publication_queued")
    assert not transition_allowed("quality_held", "published")
    assert transition_allowed("quality_held", "cancelled")


def test_mock_schedule_requires_future_timezone_aware_datetime() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    valid = ScheduleInput(
        idempotency_key="schedule_mock_key_1234",
        scheduled_at=future.astimezone(ZoneInfo("Asia/Seoul")),
        timezone="Asia/Seoul",
    )
    assert valid.scheduled_at.astimezone(UTC) > datetime.now(UTC)
    with pytest.raises(ValueError, match="timezone"):
        ScheduleInput.model_validate(
            {
                "idempotency_key": "schedule_mock_key_1234",
                "scheduled_at": "2026-10-29T09:00:00",
                "timezone": "Asia/Seoul",
            }
        )
    with pytest.raises(ValueError, match="offset"):
        ScheduleInput(
            idempotency_key="schedule_mock_key_1234",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            timezone="Asia/Seoul",
        )


def test_retry_policy_is_bounded_and_stops_for_auth_or_uncertain_outcomes() -> None:
    from woori.publication_worker import retryable

    assert retryable("failed", "timeout", 0, 2)
    assert retryable("failed", "server_failure", 1, 2)
    assert not retryable("failed", "timeout", 2, 2)
    assert not retryable("failed", "auth_failure", 0, 2)
    assert not retryable("uncertain", "uncertain", 0, 2)


def test_readonly_sync_returns_metadata_without_mutating_internal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import publications

    class FakeResult:
        def __init__(self, row: object) -> None:
            self.row = row

        def fetchone(self) -> object:
            return self.row

    class FakeRows:
        def fetchall(self) -> list[object]:
            return []

    class FakeConnection:
        audit_payload: object | None = None

        def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult | FakeRows:
            if "SELECT id,language_code,url,blog_id FROM blogger_blogs" in query:
                return FakeResult(
                    {
                        "id": "blog-uuid",
                        "language_code": "en",
                        "url": "https://test.blogspot.com",
                        "blog_id": "123",
                    }
                )
            if "FROM publishing_records" in query:
                return FakeRows()
            if "INSERT INTO audit_events" in query:
                self.audit_payload = params[-1]
                return FakeResult(None)
            raise AssertionError("unexpected database statement")

    fake_conn = FakeConnection()

    class Context:
        def __enter__(self) -> FakeConnection:
            return fake_conn

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(publications, "connection", lambda: Context())
    monkeypatch.setattr(
        publications.blogger_service,
        "posts",
        lambda *_: {
            "items": [
                {
                    "id": "remote-1",
                    "title": "Read-only",
                    "url": "https://example.com/post",
                    "content": "private body",
                }
            ],
            "nextPageToken": "page-2",
        },
    )
    result = sync_readonly(UUID("00000000-0000-0000-0000-000000000001"))
    assert result["read_only"] is True
    assert result["internal_state_changed"] is False
    assert result["posts"][0]["internal_record"] is False
    assert "content" not in result["posts"][0]
    assert result["next_page_token"] == "page-2"
    assert fake_conn.audit_payload is not None
