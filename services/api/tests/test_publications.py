from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from test_pipeline import lab as shared_lab
from woori import publication_worker, publications
from woori.publication_modes import ModeSettingsInput
from woori.publications import (
    DisabledRealBloggerPublisher,
    EmergencyStopInput,
    FakeBloggerPublisher,
    PublicationError,
    ScheduleInput,
    _assess,
    sync_readonly,
    transition_allowed,
)

lab = shared_lab


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


def test_manual_publication_requires_editorial_and_exact_version_approval() -> None:
    row = {
        "language_active": True, "blog_active": True, "version_language": "en",
        "blog_language": "en", "blog_id_value": "123456789",
        "connection_verified_at": datetime.now(UTC), "test_publish_verified_at": datetime.now(UTC),
        "oauth_status": "connected", "policy_id": "policy", "policy_active": True,
        "auto_publish_allowed": False, "machine_passed": True,
        "human_review_required": False, "human_review_approved": True,
        "publication_approval_approved": False, "publish_ready": False,
    }
    result = _assess(row)
    assert "publication_approval_missing_or_stale" in result["reasons"]
    assert result["state"] == "publication_blocked"
    row["publication_approval_approved"] = True
    approved = _assess(row)
    assert "publication_approval_missing_or_stale" not in approved["reasons"]
    assert "production_writes_disabled" in approved["reasons"]


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


def test_publication_worker_dispatches_only_explicitly_confirmed_private_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import blogger_drafts, publication_worker

    called: list[bool] = []
    monkeypatch.setattr(
        blogger_drafts,
        "process_next_queued_draft",
        lambda: called.append(True) or {"preview_id": "draft-1", "status": "succeeded"},
    )
    result = publication_worker.tick(allow_private_drafts=True)
    assert called == [True]
    assert result == {
        "job_type": "blogger_private_draft",
        "preview_id": "draft-1",
        "status": "succeeded",
        "private_draft_creation_enabled": True,
        "public_publication_enabled": False,
        "simulation_only": False,
    }


def test_mock_and_private_draft_modes_never_dispatch_publication_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from woori import blogger_drafts, publication_worker

    monkeypatch.setattr(blogger_drafts, "process_next_queued_draft", lambda: None)
    live_calls: list[bool] = []
    monkeypatch.setattr(publication_worker, "process_next_live_job",
                        lambda: live_calls.append(True) or {"status": "published"})

    class Result:
        def fetchall(self) -> list[object]:
            return []
        def fetchone(self) -> None:
            return None

    class FakeConnection:
        def execute(self, _query: str, _params: tuple[object, ...] = ()) -> Result:
            return Result()

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(publication_worker, "connection", fake_connection)

    assert publication_worker.tick(allow_private_drafts=False) is None
    assert publication_worker.tick(allow_private_drafts=True) is None
    assert live_calls == []


def test_publication_mode_defaults_manual_and_auto_requires_allowlist() -> None:
    assert ModeSettingsInput().configured_mode == "manual"
    with pytest.raises(ValidationError, match="category_allowlist"):
        ModeSettingsInput(configured_mode="auto")
    auto = ModeSettingsInput(configured_mode="auto", allowed_categories=["policy"])
    assert auto.daily_auto_limit == 1
    assert auto.minimum_interval_minutes == 1440
    assert auto.retry_limit == 0


def test_auto_mode_cannot_be_saved_until_live_publisher_and_operations_approval_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    from woori import publications

    class FakeConnection:
        def execute(self, *_: object, **__: object) -> None:
            raise AssertionError("blocked Auto settings must not write to the database")

    class Context:
        def __enter__(self) -> FakeConnection:
            return FakeConnection()

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(publications, "connection", lambda: Context())
    monkeypatch.setattr(
        publications,
        "_mode_settings",
        lambda _: {"migration_required": False, "emergency_stopped": False},
    )

    with pytest.raises(HTTPException) as caught:
        publications.save_mode_settings(
            ModeSettingsInput(configured_mode="auto", allowed_categories=["policy"])
        )

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "auto_publication_unavailable",
        "reasons": [
            "live_blogger_publisher_not_enabled",
            "operations_auto_approval_required",
        ],
        "real_writes_enabled": False,
    }


def test_mode_scope_precedence_is_blog_then_language_then_global() -> None:
    from woori.publication_modes import resolve_mode

    settings = [
        {"scope_type": "global", "scope_key": "", "configured_mode": "manual"},
        {"scope_type": "language", "scope_key": "ja", "configured_mode": "auto"},
        {"scope_type": "blog", "scope_key": "blog-1", "configured_mode": "manual"},
    ]
    assert resolve_mode(settings, "ja", "blog-1")["configured_mode"] == "manual"
    assert resolve_mode(settings, "ja", "blog-2")["configured_mode"] == "auto"
    assert resolve_mode(settings, "en", "blog-2")["configured_mode"] == "manual"


def test_auto_eligibility_never_enables_live_publication() -> None:
    from woori.publication_modes import AUTO_REQUIRED_FLAGS, assess_auto_candidate

    evidence = {key: True for key in AUTO_REQUIRED_FLAGS}
    result = assess_auto_candidate(evidence, requested_mode="auto", emergency_stopped=False)
    assert result["eligible"] is False
    assert "operations_auto_approval_required" in result["reasons"]
    assert "live_blogger_writes_disabled" in result["reasons"]
    stopped = assess_auto_candidate(evidence, requested_mode="auto", emergency_stopped=True)
    assert "emergency_stop_enabled" in stopped["reasons"]


def test_auto_candidate_fails_closed_for_missing_verification_and_publish_ready() -> None:
    from woori.publication_modes import assess_auto_candidate

    result = assess_auto_candidate(
        {"machine_passed": True}, requested_mode="auto", emergency_stopped=False
    )
    assert "seo_passed_not_verified" in result["reasons"]
    assert "source_rights_approved_not_verified" in result["reasons"]
    assert "publish_ready_not_verified" in result["reasons"]
    assert result["simulation_only"] is True


def test_emergency_stop_input_cannot_be_cleared_through_api_model() -> None:
    assert EmergencyStopInput(enabled=True).enabled is True
    with pytest.raises(ValidationError):
        EmergencyStopInput.model_validate({"enabled": False})


def test_emergency_stop_is_persisted_and_audited_in_isolated_database(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    conn, api, headers = lab

    @contextmanager
    def shared_connection():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publications, "connection", shared_connection)
    response = api.post(
        "/admin/publications/emergency-stop",
        headers=headers,
        json={"enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["emergency_stopped"] is True
    setting = conn.execute(
        "SELECT emergency_stopped,configured_mode,operations_auto_approved FROM publication_mode_settings WHERE scope_type='global' AND scope_key=''"
    ).fetchone()
    assert setting["emergency_stopped"] is True
    assert setting["configured_mode"] == "manual"
    assert setting["operations_auto_approved"] is False
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='publication.emergency_stop.engaged' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event["payload"]["emergency_stopped"] is True


def test_emergency_stop_blocks_live_job_before_any_blogger_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager
    from uuid import uuid4

    job_id, policy_id, blog_id, content_version_id, oauth_id = (uuid4() for _ in range(5))
    job = {
        "id": job_id, "policy_id": policy_id, "blog_id": blog_id,
        "content_version_id": content_version_id, "idempotency_key": "safe-stop-live-job-0001",
        "attempts": 0, "retry_count": 0, "max_retries": 0,
        "publication_state": "publication_queued", "live_stage": "draft_needed",
        "remote_post_id": None, "oauth_connection_id": oauth_id,
    }

    class Result:
        def __init__(self, row: object | None = None, rows: list[object] | None = None) -> None:
            self.row, self.rows = row, rows or []

        def fetchone(self) -> object | None:
            return self.row

        def fetchall(self) -> list[object]:
            return self.rows

    class FakeConnection:
        def execute(self, query: str, _params: object = None) -> Result:
            if "to_regclass('public.live_publication_attempts')" in query:
                return Result({"ready": "live_publication_attempts"})
            if "SELECT id,live_stage,publication_state FROM publishing_jobs" in query:
                return Result(rows=[])
            if "SELECT id,policy_id,blog_id,content_version_id" in query:
                return Result(job)
            if "SELECT oauth_connection_id,blog_id FROM blogger_blogs" in query:
                return Result({"oauth_connection_id": oauth_id, "blog_id": "blog-verified"})
            if "SELECT emergency_stopped FROM publication_mode_settings" in query:
                return Result({"emergency_stopped": True})
            return Result({"id": job_id})

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(publication_worker, "connection", fake_connection)
    monkeypatch.setattr(publications, "_candidate", lambda *_: {"id": content_version_id})
    monkeypatch.setattr(publications, "_assess", lambda *_: {"reasons": []})
    monkeypatch.setattr(publication_worker.external_policy, "_blogger_operation_is_approved", lambda _: True)
    monkeypatch.setattr(
        publication_worker, "BloggerLivePublisher",
        lambda: pytest.fail("emergency stop must block before publisher construction"),
    )

    result = publication_worker.process_next_live_job()
    assert result["status"] == "blocked"
    assert "global_emergency_stop_or_policy_missing" in result["reasons"]
    assert result["live_write_performed"] is False


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
