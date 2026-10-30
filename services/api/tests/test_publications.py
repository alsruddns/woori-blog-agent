from __future__ import annotations

import hashlib
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
    ManualLiveRequestInput,
    PublicationError,
    ScheduleInput,
    _assess,
    _has_identical_body,
    sync_readonly,
    transition_allowed,
)

lab = shared_lab


def test_remote_duplicate_unknown_uses_bounded_retry_and_found_never_retries() -> None:
    first = publication_worker.remote_duplicate_retry_plan("unknown", 0, 2)
    exhausted = publication_worker.remote_duplicate_retry_plan("unknown", 2, 2)
    duplicate = publication_worker.remote_duplicate_retry_plan("found", 0, 2)

    assert first == {"job_status": "queued", "retry": True, "retry_count": 1,
                     "delay_seconds": 60}
    assert exhausted == {"job_status": "failed", "retry": False, "retry_count": 3,
                         "delay_seconds": None}
    assert duplicate == {"job_status": "blocked", "retry": False, "retry_count": 0,
                        "delay_seconds": None}
    assert publication_worker.remote_duplicate_retry_delay(20) == 900


def test_manual_publish_reason_accepts_concise_korean_confirmation() -> None:
    payload = {
        "content_version_id": str(uuid4()),
        "blog_id": str(uuid4()),
        "expected_title_sha256": "a" * 64,
        "expected_body_sha256": "b" * 64,
        "expected_html_sha256": "c" * 64,
        "actor_label": "admin",
        "reason": "\uD655\uC778\uC644\uB8CC",
        "reviewed_exact_content": True,
        "assertions_safe_to_publish": True,
        "rights_privacy_harm_checked": True,
        "confirmation": "PUBLISH THIS EXACT MANUSCRIPT PUBLICLY",
        "idempotency_key": "manual-publish-test-1234",
    }
    request = ManualLiveRequestInput.model_validate(payload)
    assert request.reason == "\uD655\uC778\uC644\uB8CC"
    with pytest.raises(ValidationError):
        ManualLiveRequestInput.model_validate({**payload, "reason": "확인"})


def test_publication_worker_execution_mode_tracks_live_lanes() -> None:
    assert publication_worker.execution_mode() == "operations-mock-only"
    assert publication_worker.execution_mode(scheduled_auto=True) == "operations-scheduled-auto"
    assert publication_worker.execution_mode(manual_confirmed=True) == "operations-manual-confirmed"
    assert publication_worker.execution_mode(scheduled_auto=True, manual_confirmed=True) == "operations-scheduled-auto-and-manual"


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


def test_publication_read_model_uses_current_import_schema(lab: Any, monkeypatch: Any) -> None:
    from contextlib import contextmanager

    conn, api, headers = lab

    @contextmanager
    def shared_connection():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publications, "connection", shared_connection)
    response = api.get("/admin/publications", params={"view": "review"}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["view"] == "review"
    assert {"queue", "review", "published", "held"} <= set(payload["summary"])


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
    generation_method = "chatgpt_scheduled_export"
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
                    "id": import_id, "generation_method": generation_method,
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
            if "publication.auto_failure.recorded" in sql and "publication.auto_failure.cleared" in sql:
                return FakeResult(None)
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
    monkeypatch.setattr(publications, "_candidate", lambda *_args: {"content_version_id": content_version_id})
    monkeypatch.setattr(publications, "_manual_publication_snapshot", lambda *_args: {
        "title": "테스트 원고", "body": body, "title_sha256": "a" * 64,
        "body_sha256": digest, "html_sha256": "b" * 64,
        "generation_method": generation_method, "followups": [],
    })
    monkeypatch.setattr(publications, "_manual_publication_blockers", lambda *_args: [])
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"scope": ["test"]})
    monkeypatch.setattr(external_policy, "_scheduled_publication_approval", lambda _blog_id: {"scope": ["test"]})
    result = publications.scheduled_first_post_status(import_id)

    assert result["body_sha256"] == digest
    assert result["scheduled_auto_enabled"] is True
    assert result["actual_write_performed"] is False
    assert result["first_publication_approval_required"] is False
    assert result["targets"][0]["first_publication_approval_required"] is False
    assert result["targets"][0]["approval_blockers"] == []
    assert result["targets"][0]["manual_publication"]["status"] == "eligible"
    assert result["targets"][0]["manual_publication"]["generation_method"] == "chatgpt_scheduled_export"

    # Ordinary manual imports must get the same manual eligibility read model
    # even when there is no scheduled auto-failure event to recover.
    generation_method = "manual_codex_import"
    manual_result = publications.scheduled_first_post_status(import_id)
    manual_target = manual_result["targets"][0]["manual_publication"]
    assert manual_result["auto_publication_failure"] is False
    assert manual_target["status"] == "eligible"
    assert manual_target["generation_method"] == "manual_codex_import"


def test_scheduled_first_post_approval_endpoint_is_retired_without_db_write() -> None:
    from fastapi import HTTPException
    from woori.publications import ScheduledFirstPostApprovalInput, approve_scheduled_first_post

    request = ScheduledFirstPostApprovalInput(
        blog_id=uuid4(), import_id=uuid4(), import_version_id=uuid4(),
        content_version_id=uuid4(), body_sha256="a" * 64, actor_label="Operator",
        reason="Legacy endpoint retirement regression test", idempotency_key="retired-first-post-001",
        confirmation="APPROVE THIS SCHEDULED MANUSCRIPT FOR FIRST PUBLICATION",
    )
    with pytest.raises(HTTPException) as error:
        approve_scheduled_first_post(request)
    assert error.value.status_code == 410
    assert "retired" in str(error.value.detail)


def test_scheduled_auto_job_is_enqueued_without_any_first_post_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from uuid import uuid4

    from woori import content_imports

    blog_record_id = uuid4()
    import_id = uuid4()
    version_id = uuid4()
    content_version_id = uuid4()
    job_id = uuid4()
    review_id = uuid4()
    sql_seen: list[str] = []

    class Result:
        def __init__(self, one: Any = None, many: list[Any] | None = None) -> None:
            self.one, self.many = one, many or []

        def fetchone(self) -> Any:
            return self.one

        def fetchall(self) -> list[Any]:
            return self.many

    class FakeConnection:
        def execute(self, sql: str, _params: Any = None) -> Result:
            sql_seen.append(sql)
            assert "scheduled_first_publication_events" not in sql
            if "SELECT action FROM scheduled_publication_policy_events" in sql:
                return Result({"action": "enabled"})
            if "scope_type='global'" in sql:
                return Result({"emergency_stopped": False})
            if "SELECT id FROM external_content_imports" in sql:
                return Result(many=[{"id": import_id}])
            if "SELECT action,approved_blog_ids,daily_limit" in sql:
                return Result({"action": "enabled", "approved_blog_ids": [blog_record_id], "daily_limit": 1})
            if "SELECT EXISTS(SELECT 1 FROM publishing_jobs" in sql:
                return Result({"value": False})
            if "SELECT i.*,v.id AS import_version_id" in sql:
                return Result(many=[{
                    "id": import_id, "generation_method": "chatgpt_scheduled_export",
                    "language_code": "ko", "state": "awaiting_human_review",
                    "event_group_id": None, "sources": [], "claims": [],
                    "import_version_id": version_id, "version_number": 1,
                    "import_title": "Scheduled article", "title": "Scheduled article",
                    "body_markdown": "Evidence-backed test body", "blogger_labels": ["business"],
                    "import_hash": "a" * 64, "content_version_id": content_version_id,
                    "content_body": "Evidence-backed test body",
                    "blog_record_id": blog_record_id, "blog_id": "3321654108096579717",
                    "blog_language": "ko", "url": "https://trend-ko.blogspot.com",
                    "oauth_connection_id": uuid4(), "active": True,
                    "connection_verified_at": datetime.now(UTC), "oauth_status": "connected",
                    "external_content_id": uuid4(),
                }])
            if "SELECT id FROM publishing_jobs WHERE blog_id=%s AND content_version_id=%s" in sql:
                return Result(None)
            if "publication.scheduled_auto.evidence_assessed'" in sql and "SELECT 1 FROM audit_events" in sql:
                return Result(None)
            if "publication.scheduled_auto.remote_duplicate_check'" in sql and "SELECT payload" in sql:
                return Result(None)
            if "SELECT count(*)::int AS n FROM publishing_jobs WHERE publication_lane='scheduled_auto'" in sql:
                return Result({"n": 0})
            if "SELECT p.id FROM publishing_policies p JOIN language_profiles" in sql:
                return Result({"id": uuid4()})
            if "INSERT INTO publishing_jobs" in sql:
                return Result({"id": job_id})
            if "INSERT INTO post_publication_reviews" in sql:
                return Result({"id": review_id})
            if "FROM external_content_import_assessments" in sql:
                return Result({"seo_checks": []})
            return Result(None)

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(publication_worker, "connection", fake_connection)
    monkeypatch.setattr(content_imports, "prepare_scheduled_publishable_version", lambda _id: {"prepared": True})
    monkeypatch.setattr(
        publication_worker, "_scheduled_eligibility",
        lambda *_args, **_kwargs: {"reasons": [], "assessment": {"seo_checks": []}, "evidence": {
            "checks": {}, "source_ids": [], "claim_ids": [], "source_evidence_sha256": {},
            "claim_count": 0, "followups": [],
        }},
    )
    monkeypatch.setattr(publication_worker, "find_remote_duplicate", lambda *_args: {"status": "clear", "reason": None})
    result = publication_worker.enqueue_scheduled_auto_jobs()
    assert result["created"] == 1
    assert result["held"] == 0
    assert result["first_publication_approval_required"] is False
    assert any("INSERT INTO publishing_jobs" in sql for sql in sql_seen)


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


@pytest.mark.parametrize(('language','country'), [('ko','KR'),('en','US'),('ja','JP'),('zh-CN','CN')])
def test_manual_live_request_commits_approval_job_and_followups_atomically_in_isolated_db(
    lab: Any, monkeypatch: pytest.MonkeyPatch, language: str, country: str,
) -> None:
    """Exercise the production POST SQL and schema guards inside the lab rollback boundary."""
    from contextlib import contextmanager

    from psycopg.types.json import Jsonb
    from woori.google_http import WRITE_SCOPE

    conn, api, headers = lab
    profile = conn.execute(
        "INSERT INTO language_profiles(language_code,target_country) VALUES (%s,%s) ON CONFLICT(language_code,target_country) DO UPDATE SET search_intent=language_profiles.search_intent RETURNING id",
        (language,country),
    ).fetchone()["id"]
    oauth_id = uuid4()
    blog_record_id = uuid4()
    blog_id = "9876543210123456789"
    conn.execute(
        "INSERT INTO google_connections(id,label,status,scopes) VALUES (%s,'isolated fixture','connected',%s)",
        (oauth_id, [WRITE_SCOPE]),
    )
    conn.execute(
        """INSERT INTO blogger_blogs(id,language_code,url,display_name,active,blog_id,
             connection_verified_at,test_publish_verified_at,oauth_connection_id)
           VALUES (%s,%s,'https://manual-transaction-fixture.blogspot.com',
             'Isolated manual transaction fixture',true,%s,now(),now(),%s)""",
        (blog_record_id, language, blog_id, oauth_id),
    )
    policy_id = uuid4()
    conn.execute(
        """INSERT INTO publishing_policies(id,language_code,blog_id,profile_id,active)
           VALUES (%s,%s,%s,%s,false)""",
        (policy_id, language, blog_record_id, conn.execute(
            "SELECT id FROM language_profiles WHERE language_code=%s AND target_country=''",
            (language,),
        ).fetchone()['id']),
    )
    group_id, localization_id, version_id, import_id, import_version_id = (uuid4() for _ in range(5))
    title = "Isolated manual publication transaction"
    body = "A synthetic body used only to exercise the transaction in a forced-rollback test."
    conn.execute("INSERT INTO content_groups(id) VALUES (%s)", (group_id,))
    conn.execute(
        "INSERT INTO content_localizations(id,group_id,language_code,target_country) VALUES (%s,%s,%s,%s)",
        (localization_id, group_id, language, country),
    )
    conn.execute(
        """INSERT INTO content_versions(id,group_id,language,localization_id,version,title,body)
           VALUES (%s,%s,%s,%s,1,%s,%s)""",
        (version_id, group_id, language, localization_id, title, body),
    )
    digest = hashlib.sha256((title + "\n" + body + "\n{}\n[]").encode()).hexdigest()
    conn.execute(
        """INSERT INTO external_content_imports
           (id,external_content_id,event_group_id,relation,source_region,language_code,
            target_audiences,category,title,body_markdown,source_ids,sources,claims,
            fact_checked_at,seo_metadata,blogger_labels,generation_method,generated_at,
            submitted_by,content_sha256,idempotency_key)
           VALUES (%s,%s,%s,'original',%s,%s,%s,'finance',%s,%s,'[]','[]','[]',now(),
             '{}','[]','manual_codex_import',now(),'isolated-test',%s,%s)""",
        (import_id, str(import_id), "manual-test-" + str(import_id),country,language,
         Jsonb([{"language_code": language, "target_region": country}]), title, body,
         digest, hashlib.sha256(("import" + str(import_id)).encode()).hexdigest()),
    )
    conn.execute(
        """INSERT INTO external_content_import_versions
           (id,import_id,version_number,title,body_markdown,seo_metadata,blogger_labels,
            content_sha256,author_label,change_reason)
           VALUES (%s,%s,1,%s,%s,'{}','[]',%s,'isolated-test','transaction integration test')""",
        (import_version_id, import_id, title, body, digest),
    )
    conn.execute(
        "INSERT INTO external_content_import_content_links(import_id,import_version_id,content_version_id) VALUES (%s,%s,%s)",
        (import_id, import_version_id, version_id),
    )

    @contextmanager
    def shared_connection():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(publications, "connection", shared_connection)
    monkeypatch.setattr(publications.external_policy, "_blogger_policy_approval", lambda: {"approved": True})
    monkeypatch.setattr(publications.BloggerLivePublisher, "_target", staticmethod(lambda _blog: None))

    candidate = publications._candidate(conn, version_id, blog_record_id)
    assert candidate is not None and candidate['policy_id'] is None
    missing_policy = publications._manual_publication_snapshot(conn, candidate)
    assert 'publication_policy_missing' in publications._manual_publication_blockers(
        conn, candidate, missing_policy, blog_record_id,
    )
    conn.execute(
        "INSERT INTO publishing_policies(language_code,blog_id,profile_id,active) VALUES (%s,%s,%s,false)",
        (language,blog_record_id,profile),
    )
    candidate = publications._candidate(conn, version_id, blog_record_id)
    snapshot = publications._manual_publication_snapshot(conn, candidate)
    other_blog = conn.execute("SELECT id FROM blogger_blogs WHERE language_code<>%s LIMIT 1", (language,)).fetchone()['id']
    wrong = publications._candidate(conn, version_id, other_blog)
    assert 'blog_language_mismatch' in publications._manual_publication_blockers(
        conn, wrong, publications._manual_publication_snapshot(conn, wrong), other_blog,
    )
    payload = {
        "content_version_id": str(version_id), "blog_id": str(blog_record_id),
        "expected_title_sha256": snapshot["title_sha256"],
        "expected_body_sha256": snapshot["body_sha256"],
        "expected_html_sha256": snapshot["html_sha256"], "actor_label": "admin",
        "reason": "확인완료", "reviewed_exact_content": True,
        "assertions_safe_to_publish": True, "rights_privacy_harm_checked": True,
        "confirmation": "PUBLISH THIS EXACT MANUSCRIPT PUBLICLY",
        "idempotency_key": "isolated-manual-post-" + uuid4().hex[:20],
    }
    first = api.post("/admin/publications/manual-live-requests", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["public_write_performed"] is False
    assert first.json()["followup_review_id"]
    assert conn.execute("SELECT count(*) AS n FROM publishing_jobs WHERE idempotency_key=%s",
                        (payload["idempotency_key"],)).fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM manual_publication_approval_events WHERE idempotency_key=%s",
                        (payload["idempotency_key"],)).fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM post_publication_reviews WHERE publishing_job_id=%s",
                        (first.json()["id"],)).fetchone()["n"] == 1
    again = api.post("/admin/publications/manual-live-requests", headers=headers, json=payload)
    assert again.status_code == 201 and again.json()["duplicate"] is True
    recovery_job = UUID(first.json()['id'])
    draft_payload = {'title': snapshot['title'], 'content': snapshot['safe_html']}
    fingerprint = publications.BloggerLivePublisher._fingerprint('create_draft', blog_id, draft_payload)
    conn.execute("INSERT INTO blogger_write_operations(idempotency_key,request_fingerprint,operation,status) VALUES (%s,%s,'create_draft','failed')",
                 ('live:pubjob-' + str(recovery_job) + '-draft',fingerprint))
    conn.execute("UPDATE publishing_jobs SET status='failed',publication_state='publication_failed' WHERE id=%s", (recovery_job,))
    monkeypatch.setattr(publication_worker, 'connection', shared_connection)
    monkeypatch.setattr(publications.BloggerLivePublisher, '_target', staticmethod(lambda _blog: {'blog_id':blog_id}))
    monkeypatch.setattr('woori.blogger_service.post', lambda *_: {
        'id':'123456', 'blog':{'id':blog_id}, 'status':'DRAFT', **draft_payload})
    recovered = publication_worker.reconcile_manual_draft(recovery_job, '123456')
    assert recovered['status'] == 'queued' and recovered['blogger_write_performed'] is False
    with pytest.raises(Exception, match='manual_failed_job_required'):
        publication_worker.reconcile_manual_draft(recovery_job, '123456')
    published = {'post_id':'123456', 'blog_id':blog_id, 'status':'LIVE',
                 'url':'https://manual-transaction-fixture.blogspot.com/verified.html',
                 'published_at':datetime.now(UTC).isoformat()}
    conn.execute("INSERT INTO blogger_write_operations(idempotency_key,request_fingerprint,operation,status,result) VALUES (%s,%s,'publish_draft','succeeded',%s)",
                 ('live:pubjob-' + str(recovery_job) + '-publish','test-publish-fingerprint',Jsonb(published)))
    monkeypatch.setattr('woori.blogger_service.post', lambda *_: {
        'id':'123456', 'blog':{'id':blog_id},'status':'LIVE','url':published['url'],**draft_payload})
    assert publication_worker.reconcile_published_manual_job(recovery_job)['status'] == 'published'
    assert publication_worker.reconcile_published_manual_job(recovery_job)['status'] == 'published'
    assert conn.execute('SELECT count(*) n FROM publishing_records WHERE job_id=%s',(recovery_job,)).fetchone()['n'] == 1
    assert conn.execute('SELECT post_id FROM post_publication_reviews WHERE publishing_job_id=%s',(recovery_job,)).fetchone()['post_id'] == '123456'
    assert conn.execute("SELECT count(*) AS n FROM publishing_jobs WHERE idempotency_key=%s",
                        (payload["idempotency_key"],)).fetchone()["n"] == 1


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
