from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
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
    _has_identical_body,
    sync_readonly,
    transition_allowed,
)

lab = shared_lab


def test_same_event_dedup_requires_identical_body() -> None:
    candidate = "FOMC held the target range.\n[source:statement]"
    assert _has_identical_body(candidate, [candidate])
    assert not _has_identical_body(candidate, ["FOMC held rates; this analysis differs."])
    assert not _has_identical_body(candidate, [])


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


def test_candidate_query_parses_and_returns_none_for_unknown_ids(lab: Any) -> None:
    conn, _, _ = lab
    assert publications._candidate(conn, uuid4(), uuid4()) is None


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


def test_scheduled_first_post_status_exposes_exact_blockers_without_writing(monkeypatch: Any) -> None:
    import hashlib
    from contextlib import contextmanager

    from woori import external_policy

    import_id, import_version_id, content_version_id, blog_record_id = (uuid4() for _ in range(4))
    body = "검증된 예약 원고 본문"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    blog_api_id = "3321654108096579717"
    class FakeResult:
        def __init__(self, one: Any = None, many: list[Any] | None = None) -> None:
            self.one, self.many = one, many or []

        def fetchone(self) -> Any:
            return self.one

        def fetchall(self) -> list[Any]:
            return self.many

    class FakeConnection:
        def execute(self, sql: str, params: Any = None) -> FakeResult:
            if "FROM external_content_imports i" in sql:
                return FakeResult({
                    "id": import_id, "generation_method": "chatgpt_scheduled_export",
                    "language_code": "ko", "import_title": "테스트 예약 원고",
                    "import_version_id": import_version_id, "version_number": 1,
                    "title": "테스트 예약 원고", "body_markdown": body,
                    "content_sha256": digest, "content_version_id": content_version_id,
                })
            if "FROM external_content_import_assessments" in sql:
                return FakeResult({"id": uuid4(), "machine_passed": True, "publish_ready": False})
            if "FROM external_content_import_review_events" in sql:
                return FakeResult({"event_type": "editorial_review_passed", "reviewer_label": "editor",
                                   "sources_examined": True, "claims_checked": True, "rights_reviewed": True})
            if "FROM scheduled_publication_policy_events" in sql and "ORDER BY id DESC LIMIT 1" in sql:
                return FakeResult({"id": 1, "action": "enabled", "approved_blog_ids": [blog_record_id],
                                   "daily_limit": 1, "actor_label": "owner", "reason": "test"})
            if "SELECT EXISTS(SELECT 1 FROM publishing_jobs" in sql:
                return FakeResult({"any_published": False})
            if "FROM scheduled_first_publication_events e" in sql and "NOT EXISTS" in sql:
                return FakeResult(None)
            if "FROM scheduled_publication_policy_events" in sql and "LIMIT 20" in sql:
                return FakeResult(many=[])
            if "FROM scheduled_first_publication_events" in sql and "LIMIT 20" in sql:
                return FakeResult(many=[])
            if "publication.scheduled_auto.connection_check" in sql:
                return FakeResult(None)
            if "scope_type='global'" in sql:
                return FakeResult({"emergency_stopped": False})
            if "FROM audit_events" in sql and "publication.scheduled_auto.evidence_assessed" in sql:
                return FakeResult({"payload": {"status": "passed", "reasons": []}, "created_at": datetime.now(UTC)})
            if "FROM blogger_blogs b LEFT JOIN google_connections" in sql:
                from woori.google_http import WRITE_SCOPE
                return FakeResult(many=[{
                    "id": blog_record_id, "blog_id": blog_api_id, "language_code": "ko",
                    "display_name": "한국어 블로그", "url": "https://trend-ko.blogspot.com",
                    "active": True, "connection_verified_at": None, "oauth_status": "connected",
                    "scopes": [WRITE_SCOPE],
                }])
            if "FROM publishing_jobs j LEFT JOIN publishing_records" in sql:
                return FakeResult(many=[])
            raise AssertionError(f"Unexpected query in read-only status test: {sql}")

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(publications, "connection", fake_connection)
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"scope": ["test"]})
    monkeypatch.setattr(external_policy, "_scheduled_publication_approval", lambda _blog_id: {"scope": ["test"]})
    result = publications.scheduled_first_post_status(import_id)

    assert result["body_sha256"] == digest
    assert result["scheduled_auto_enabled"] is True
    assert result["actual_write_performed"] is False
    assert result["targets"][0]["can_record_first_approval"] is True
    assert result["targets"][0]["approval_blockers"] == []


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
    monkeypatch.setattr(publication_worker, "enqueue_scheduled_auto_jobs", lambda: {"created": 0})

    assert publication_worker.tick(allow_private_drafts=False) is None
    assert publication_worker.tick(allow_private_drafts=True) is None
    assert live_calls == []


def test_manual_confirmed_lane_is_opt_in_and_kept_separate_from_scheduled_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import publication_worker

    calls: list[dict[str, bool]] = []
    monkeypatch.setattr(
        publication_worker,
        "process_next_live_job",
        lambda **kwargs: calls.append(kwargs) or {"status": "queued"},
    )
    result = publication_worker.tick(allow_manual_confirmed_publications=True)
    assert result is not None
    assert result["job_type"] == "manual_confirmed_blogger_live"
    assert calls == [{"manual_confirmed_only": True}]

    calls.clear()
    result = publication_worker.tick(allow_scheduled_auto_publications=True)
    assert result is not None
    assert result["job_type"] == "scheduled_auto_blogger_live"
    assert calls == [{"scheduled_auto_only": True}]


def test_publication_mode_defaults_manual_and_auto_requires_allowlist() -> None:
    assert ModeSettingsInput().configured_mode == "manual"
    with pytest.raises(ValidationError, match="category_allowlist"):
        ModeSettingsInput(configured_mode="auto")
    auto = ModeSettingsInput(configured_mode="auto", allowed_categories=["policy"])
    assert auto.daily_auto_limit == 1
    assert auto.minimum_interval_minutes == 1440
    assert auto.retry_limit == 0


def test_auto_mode_preferences_can_be_saved_without_activating_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import publications

    class FakeConnection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, query: str, *_: object, **__: object) -> Any:
            self.statements.append(query)

            class Result:
                def fetchall(self) -> list[dict[str, str]]:
                    return [{"slug": "policy"}]

                def fetchone(self) -> dict[str, Any]:
                    return {
                        "scope_type": "global", "scope_key": "", "configured_mode": "auto",
                        "daily_auto_limit": 1, "minimum_interval_minutes": 1440,
                        "allowed_start_hour": 9, "allowed_end_hour": 17,
                        "timezone": "Asia/Seoul", "allowed_categories": ["policy"],
                        "excluded_topics": [], "max_source_age_hours": 24,
                        "retry_limit": 0, "emergency_stopped": False,
                        "operations_auto_approved": False, "updated_at": None,
                    }

            return Result()

    fake_conn = FakeConnection()

    class Context:
        def __enter__(self) -> FakeConnection:
            return fake_conn

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(publications, "connection", lambda: Context())
    monkeypatch.setattr(
        publications,
        "_mode_settings",
        lambda _: {"migration_required": False, "emergency_stopped": False},
    )

    result = publications.save_mode_settings(
        ModeSettingsInput(configured_mode="auto", allowed_categories=["policy"])
    )
    assert result["configured_mode"] == "auto"
    assert result["live_auto_enabled"] is False
    assert result["real_writes_enabled"] is False
    assert result["operations_auto_approved"] is False
    assert any("publication.mode.changed" in statement for statement in fake_conn.statements)


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
    from datetime import UTC, datetime, timedelta

    from woori.publication_modes import AUTO_REQUIRED_FLAGS, assess_auto_candidate

    evidence = {key: True for key in AUTO_REQUIRED_FLAGS}
    evidence.update({"category": "finance", "topic": "markets"})
    now = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    policy = {"allowed_categories": ["finance"], "daily_auto_limit": 1,
              "minimum_interval_minutes": 5, "timezone": "Asia/Seoul",
              "allowed_start_hour": 0, "allowed_end_hour": 23}
    result = assess_auto_candidate(
        evidence, requested_mode="auto", emergency_stopped=False, settings=policy,
        daily_published_count=0, last_published_at=now - timedelta(minutes=6), now=now,
    )
    assert result["auto_eligible"] is True
    assert result["human_review_required"] is False
    assert result["human_approval_recorded"] is False
    assert result["dispatchable"] is False
    assert "live_blogger_writes_disabled" in result["reasons"]
    stopped = assess_auto_candidate(evidence, requested_mode="auto", emergency_stopped=True)
    assert "emergency_stop_enabled" in stopped["reasons"]


def test_auto_candidate_fails_closed_for_missing_verification_and_publish_ready() -> None:
    from woori.publication_modes import assess_auto_candidate

    result = assess_auto_candidate(
        {"machine_passed": True}, requested_mode="auto", emergency_stopped=False
    )
    assert "claim_evidence_semantically_verified_not_verified" in result["reasons"]
    assert "source_rights_cleared_not_verified" in result["reasons"]
    assert "language_quality_passed_not_verified" in result["reasons"]
    assert "editorial_review_passed_not_verified" not in result["reasons"]
    assert "publish_ready_not_verified" not in result["reasons"]
    assert result["auto_eligible"] is False
    assert result["simulation_only"] is True


def test_emergency_stop_input_cannot_be_cleared_through_api_model() -> None:
    assert EmergencyStopInput(enabled=True).enabled is True
    with pytest.raises(ValidationError):
        EmergencyStopInput.model_validate({"enabled": False})


def test_publication_worker_continuous_loop_has_singleton_and_graceful_idle_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    ticks: list[dict[str, Any]] = []
    monkeypatch.setattr(publication_worker, "acquire_process_lock", lambda _name: events.append("lock") or object())
    monkeypatch.setattr(publication_worker, "release_process_lock", lambda _guard, _name: events.append("unlock"))
    monkeypatch.setattr(
        publication_worker, "heartbeat",
        lambda status, *_args, **_kwargs: events.append(status),
    )
    monkeypatch.setattr(publication_worker, "consume_worker_stop_request", lambda **_kwargs: False)

    def idle_tick(*args: Any, **kwargs: Any) -> None:
        ticks.append({"args": args, **kwargs})

    monkeypatch.setattr(publication_worker, "tick", idle_tick)
    publication_worker.run_forever(poll_seconds=1, cycle_limit=1)

    assert ticks == [{"args": (30,), "allow_private_drafts": False,
                      "allow_live_publications": False,
                      "allow_scheduled_auto_publications": False,
                      "allow_manual_confirmed_publications": False}]
    assert events[0] == "lock"
    assert "running" in events
    assert events[-2:] == ["stopped", "unlock"]


def test_publication_worker_honors_stop_marker_between_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(publication_worker, "acquire_process_lock", lambda _name: object())
    monkeypatch.setattr(publication_worker, "release_process_lock", lambda _guard, _name: events.append("unlock"))
    monkeypatch.setattr(
        publication_worker, "heartbeat",
        lambda status, *_args, **_kwargs: events.append(status),
    )
    monkeypatch.setattr(publication_worker, "consume_worker_stop_request", lambda **_kwargs: True)
    monkeypatch.setattr(
        publication_worker, "tick",
        lambda *_args, **_kwargs: pytest.fail("stop marker must prevent another queue cycle"),
    )

    publication_worker.run_forever(poll_seconds=1)

    assert events[-2:] == ["stopped", "unlock"]


def test_publication_worker_status_distinguishes_empty_enabled_lane(
    lab: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    conn, _api, _headers = lab

    @contextmanager
    def shared_connection():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publications, "connection", shared_connection)
    result = publications.publication_worker_status()

    assert result["queue"]["mock_queued"] == 0
    assert result["queue"]["live_queued"] == 0
    assert result["idle_reason_if_processed_false"] == "no_queued_job_in_enabled_lane"
    assert result["live_publication_dispatch_enabled"] is False
    assert result["real_writes_enabled"] is False


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
        "publication_lane": "manual",
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
            if "FROM manual_publication_approval_events" in query:
                return Result({
                        "job_id": job_id, "blog_id": blog_id,
                        "content_version_id": content_version_id,
                    "title_sha256": "a" * 64, "body_sha256": "b" * 64,
                    "html_sha256": "c" * 64, "reviewed_exact_content": True,
                    "assertions_safe_to_publish": True, "rights_privacy_harm_checked": True,
                })
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
    monkeypatch.setattr(publications, "_manual_publication_snapshot", lambda *_: {
        "title": "A title", "body": "A body", "safe_html": "<p>A body</p>",
        "blogger_labels": [], "title_sha256": "a" * 64, "body_sha256": "b" * 64,
        "html_sha256": "c" * 64, "followups": [],
    })
    monkeypatch.setattr(publications, "_manual_publication_blockers", lambda *_args, **_kwargs: [])
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
