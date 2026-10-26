from __future__ import annotations

from datetime import UTC, datetime

import pytest
from woori.publications import (
    DisabledRealBloggerPublisher,
    FakeBloggerPublisher,
    PublicationError,
    _assess,
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
