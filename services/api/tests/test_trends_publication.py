from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from woori import external_policy
from woori.publications import TrendsAutoPolicyInput
from woori.trends_publication import (
    claims_are_publish_verified,
    enqueue_trends_auto_jobs,
    search_description_is_publishable,
)


def test_all_unverified_japan_claims_block_trends_publication() -> None:
    claims = [
        {"claim_id": f"c{index}", "source_ids": ["s1"],
         "verification_status": "unverified", "factual_state": "unverified"}
        for index in range(7)
    ]
    assert not claims_are_publish_verified(claims)


@pytest.mark.parametrize("claims", [None, [], [{}], [{"claim_id": "c1", "source_ids": ["s1"],
    "verification_status": "source_span_verified", "factual_state": "unverified"}]])
def test_empty_or_unverified_claim_sets_fail_closed(claims) -> None:
    assert not claims_are_publish_verified(claims)


def test_only_explicit_verified_claims_are_eligible() -> None:
    assert claims_are_publish_verified([
        {"claim_id": "c1", "source_ids": ["s1"],
         "verification_status": "source_span_verified", "factual_state": "approved"},
        {"claim_id": "c2", "source_ids": ["s1", "s2"],
         "verification_status": "corroborated", "factual_state": "enacted"},
    ])


def test_blogger_search_description_limit_is_150_characters() -> None:
    assert search_description_is_publishable("설명" * 30)
    assert search_description_is_publishable("a" * 150)
    assert not search_description_is_publishable("a" * 151)
    assert not search_description_is_publishable("")


def test_cn_cannot_be_added_as_unregistered_trends_region() -> None:
    with pytest.raises(ValueError):
        TrendsAutoPolicyInput(
            blog_id=uuid4(), enabled=True, allowed_geos=["CN"], daily_limit=3,
            actor_label="operator", reason="explicit policy scope validation",
            idempotency_key="trends-policy-cn-0001",
            confirmation="ENABLE TRENDS AUTO PUBLICATION",
        )


def test_trends_auto_policy_defaults_to_unlimited_and_accepts_none() -> None:
    request = TrendsAutoPolicyInput(
        blog_id=uuid4(), enabled=True, allowed_geos=["KR"], daily_limit=None,
        actor_label="operator", reason="P092 explicitly removes Trends volume caps",
        idempotency_key="trends-policy-unlimited-001",
        confirmation="ENABLE TRENDS AUTO PUBLICATION",
    )
    assert request.daily_limit is None


def test_trends_policy_needs_separate_public_write_approval(monkeypatch) -> None:
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"scope": ["blogger_read"]})
    monkeypatch.setattr(external_policy, "_blogger_public_publish_approval", lambda: None)
    monkeypatch.setattr(external_policy, "_trends_publication_approval", lambda _blog: {"scope": ["trends_auto"]})
    with external_policy.trends_publication_context(str(uuid4())):
        assert not external_policy._blogger_operation_is_approved("blogger_public_publish")


def test_trends_policy_requires_both_explicit_public_and_trends_scope(monkeypatch) -> None:
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"scope": ["blogger_read"]})
    monkeypatch.setattr(external_policy, "_blogger_public_publish_approval", lambda: {"scope": ["public_post_publish"]})
    monkeypatch.setattr(external_policy, "_trends_publication_approval", lambda _blog: {"scope": ["trends_auto"]})
    with external_policy.trends_publication_context(str(uuid4())):
        assert external_policy._blogger_operation_is_approved("blogger_public_publish")


def test_authenticated_scoped_trends_consent_never_authorizes_another_lane(monkeypatch) -> None:
    blog = str(uuid4())
    monkeypatch.setattr(external_policy, "_blogger_policy_approval", lambda: {"scope": ["blogger_read"]})
    monkeypatch.setattr(external_policy, "_blogger_public_publish_approval", lambda: None)
    monkeypatch.setattr(external_policy, "_trends_public_write_approval", lambda value: {"scope": ["trends_auto"]} if value == blog else None)
    monkeypatch.setattr(external_policy, "_trends_publication_approval", lambda value: {"scope": ["trends_auto"]})
    with external_policy.trends_publication_context(blog):
        assert external_policy._blogger_operation_is_approved("blogger_public_publish")
    with external_policy.trends_publication_context(str(uuid4())):
        assert not external_policy._blogger_operation_is_approved("blogger_public_publish")
    assert not external_policy._blogger_operation_is_approved("blogger_public_publish")


class _Result:
    def __init__(self, row: Any = None, rows: list[Any] | None = None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _TrendsEnqueueConnection:
    def __init__(self, claims: list[dict[str, Any]]):
        self.claims = claims
        self.statements: list[str] = []
        self.blog_id = uuid4()
        self.version_id = uuid4()
        self.import_id = uuid4()
        self.request_id = uuid4()
        self.topic_id = uuid4()

    def execute(self, query: str, _params: Any = None):
        self.statements.append(query)
        if "pg_advisory_xact_lock" in query:
            return _Result()
        if "SELECT emergency_stopped FROM publication_mode_settings" in query:
            return _Result({"emergency_stopped": False})
        if "FROM trends_publication_policy_events p JOIN blogger_blogs" in query:
            return _Result(rows=[{"blog_id": self.blog_id, "language_code": "ja",
                                 "blogger_id": "123456", "enabled": True,
                                 "allowed_geos": ["JP"], "daily_limit": 3,
                                 "created_at": datetime.fromisoformat("2026-10-31T08:00:00+09:00")}])
        if "FROM external_content_imports i" in query:
            return _Result(rows=[{
                "id": self.import_id, "external_content_id": "trend-test-1",
                "generation_method": "codex_trends_export", "claims": self.claims,
                "sources": [{"source_id": "s1", "url": "https://source.example/"}],
                "seo_metadata": {"search_description": "A valid Japanese search description for this article."},
                "import_version_id": uuid4(), "version_number": 1,
                "import_hash": "a" * 64, "content_version_id": self.version_id,
                "group_id": uuid4(), "localization_id": uuid4(), "content_version": 1,
                "authoring_job_id": uuid4(), "job_type": "google_trends",
                "authoring_state": "imported_review", "authoring_evidence": {},
                "authoring_error": None, "trend_request_id": self.request_id,
                "contract": {"source_country": "JP", "target_country": "JP",
                             "target_language": "ja", "target_blog_id": str(self.blog_id),
                             "collection_slot": "2026-10-31T09:00:00+09:00"},
                "trend_topic_id": self.topic_id, "blog_record_id": self.blog_id,
                "blog_id": "123456", "blog_language": "ja", "active": True,
                "connection_verified_at": "verified", "test_publish_verified_at": "verified",
                "oauth_connection_id": uuid4(), "oauth_status": "connected",
                "scopes": ["https://www.googleapis.com/auth/blogger"],
                "machine_passed": True, "safe_html": "<p>Reviewed article</p>",
                "html_sha256": "b" * 64, "seo_checks": [],
                "content_language": "ja", "target_country": "JP",
            }])
        if "FROM trend_blog_geo_authoring" in query:
            return _Result({"1": 1})
        if "SELECT id,status FROM publishing_jobs" in query:
            return _Result()
        if "FROM content_versions WHERE group_id" in query:
            return _Result({"id": self.version_id})
        if "FROM external_content_import_review_events" in query:
            return _Result()
        if "research.source.live_document_verified" in query:
            return _Result(rows=[])
        if "SELECT event_type,payload FROM audit_events" in query:
            return _Result()
        return _Result()


def test_unverified_trends_import_is_held_without_creating_job(monkeypatch) -> None:
    claim_list = [{"claim_id": f"jp-{index}", "source_ids": ["s1"],
                   "verification_status": "unverified", "factual_state": "unverified"}
                  for index in range(7)]
    fake = _TrendsEnqueueConnection(claim_list)

    @contextmanager
    def transaction():
        yield fake

    monkeypatch.setattr("woori.trends_publication.connection", transaction)
    result = enqueue_trends_auto_jobs()
    assert result == {"created": 0, "held": 1}
    assert any("publication.auto_failure.recorded" in query for query in fake.statements)
    assert not any("INSERT INTO publishing_jobs" in query for query in fake.statements)
