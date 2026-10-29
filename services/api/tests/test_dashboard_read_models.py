from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Self
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from woori import research_routes
from woori.config import settings
from woori.main import app


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _EvaluationConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.version_id = uuid4()
        self.evaluation_id = uuid4()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, _params: Any = None) -> _Cursor:
        self.statements.append(query)
        if "current_database()" in query:
            return _Cursor([{"db": "woori_blog_agent_eval", "role": "woori_eval_reader"}])
        if "count(*)::int AS total" in query:
            return _Cursor([{"total": 0 if "lower(COALESCE(model" in query else 1}])
        if "FROM research_experiment_evaluations e" in query:
            return _Cursor([{
                "id": self.evaluation_id,
                "experiment_id": uuid4(),
                "run_id": uuid4(),
                "content_version_id": self.version_id,
                "language": "en",
                "variant": "baseline",
                "mechanical_gate_passed": False,
                "human_review_required": True,
                "created_at": datetime.now(UTC),
                "provider": "local",
                "model": "qwen3",
                "title": "Stored comparison fixture",
            }])
        if "DISTINCT language_code" in query:
            return _Cursor([{"language_code": "en"}])
        if "DISTINCT category_slug" in query:
            return _Cursor([{"category_slug": "finance"}])
        if "SELECT * FROM (" in query:
            if "lower(COALESCE(model" in query:
                return _Cursor([])
            return _Cursor([{
                "evaluation_id": self.evaluation_id,
                "content_version_id": self.version_id,
                "language_code": "en",
                "topic": "Federal Reserve test",
                "topic_key": "test-topic",
                "title": "Read model fixture",
                "summary": "summary",
                "model": "qwen-local",
                "machine_passed": False,
                "human_review_required": True,
                "status": "quality_held",
                "created_at": datetime.now(UTC),
                "content_version": 1,
                "category_slug": "finance",
            }])
        raise AssertionError(f"Unexpected evaluation query: {query}")


class _OperationsConnection:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, _params: Any = None) -> _Cursor:
        if "to_regclass('public.trend_observations')" in query:
            return _Cursor([{"table_name": "trend_observations"}])
        if "to_regclass('public.trend_research_packages')" in query:
            return _Cursor([{"table_name": "trend_research_packages"}])
        if "count(*)::int AS total" in query:
            return _Cursor([{"total": 1}])
        if "FROM trend_observations o" in query and "LIMIT %s OFFSET %s" in query:
            return _Cursor([{
                "id": uuid4(), "query": "real source observation", "geo": "KR",
                "platform": "google_trends", "source_rank": None,
                "source_volume_label": None, "source_language": None,
                "source_url": "https://trends.google.com/trending/rss?geo=KR",
                "collected_at": datetime.now(UTC), "source_updated_at": None,
                "topic_id": None, "representative_query": None,
                "grouping_status": None, "topic_score": None,
                "topic_decision": None, "package_status": None,
                "verified_fact_count": None, "independent_source_count": None,
                "linked_manuscript_count": 0,
            }])
        return _Cursor([])


def test_manuscript_list_is_paginated_and_excludes_body_and_json(
    monkeypatch: Any,
) -> None:
    evaluation = _EvaluationConnection()
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: evaluation)

    @contextmanager
    def operations() -> Iterator[_OperationsConnection]:
        yield _OperationsConnection()

    monkeypatch.setattr(research_routes, "connection", operations)
    headers = {"Authorization": f"Bearer {settings().admin_token}"}
    with TestClient(app) as client:
        response = client.get(
            "/admin/research/manuscripts?page=1&page_size=10&language=en&category=finance",
            headers=headers,
        )
        archived = client.get(
            "/admin/research/manuscripts?page=1&page_size=10&language=en&category=finance&include_retired_models=true",
            headers=headers,
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0 and payload["page_size"] == 10
    assert archived.status_code == 200
    assert archived.json()["total"] == 1
    assert archived.json()["items"][0]["title"] == "Read model fixture"
    assert archived.json()["items"][0]["publish_ready"] is False
    assert not {"body", "saved_body", "metrics", "checks"}.intersection(archived.json()["items"][0])
    assert any("LIMIT %s OFFSET %s" in query for query in evaluation.statements)
    assert all("v.body" not in query for query in evaluation.statements)


def test_trend_list_keeps_unavailable_source_rank_null(monkeypatch: Any) -> None:
    @contextmanager
    def operations() -> Iterator[_OperationsConnection]:
        yield _OperationsConnection()

    monkeypatch.setattr(research_routes, "connection", operations)
    headers = {"Authorization": f"Bearer {settings().admin_token}"}
    with TestClient(app) as client:
        response = client.get("/admin/research/trend-observations?page=1&page_size=10&geo=KR", headers=headers)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["source_rank"] is None
    assert item["source_language"] is None
    assert response.json()["total"] == 1


def test_trend_detail_distinguishes_automated_source_screen_from_human_review(
    monkeypatch: Any,
) -> None:
    observation_id, topic_id, source_id = uuid4(), uuid4(), uuid4()
    statements: list[str] = []

    class DetailConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, query: str, _params: Any = None) -> _Cursor:
            statements.append(query)
            if "to_regclass('public.trend_research_packages')" in query:
                return _Cursor([{"table_name": "trend_research_packages"}])
            if "to_regclass('public.trend_topic_category_reviews')" in query:
                return _Cursor([{"relation": None}])
            if "SELECT * FROM trend_observations" in query:
                return _Cursor([{"id": observation_id, "query": "TW source signal"}])
            if "FROM trend_topic_memberships m JOIN trend_topics t" in query:
                return _Cursor([{"id": topic_id, "representative_query": "TW source signal"}])
            if "FROM trend_topic_sources ts JOIN research_sources s" in query:
                return _Cursor([{
                    "source_id": source_id,
                    "source_name": "Official source fixture",
                    "approved": True,
                    "review_actor": "collector:test-provider",
                    "review_reason": "Automated provenance only; human review pending.",
                }])
            if "FROM trend_research_packages WHERE topic_id" in query:
                return _Cursor([])
            if "FROM evidence_facts WHERE id=ANY" in query:
                return _Cursor([])
            if "FROM article_quality_evaluations q WHERE" in query:
                return _Cursor([])
            raise AssertionError(f"Unexpected query: {query}")

    @contextmanager
    def operations() -> Iterator[DetailConnection]:
        yield DetailConnection()

    monkeypatch.setattr(research_routes, "connection", operations)
    result = research_routes.trend_observation_detail(observation_id)

    assert result["sources"][0]["review_actor"] == "collector:test-provider"
    assert result["sources"][0]["review_reason"].startswith("Automated provenance only")
    assert any("LEFT JOIN LATERAL" in query and "reviewer,reason" in query for query in statements)


def test_model_comparison_read_model_uses_isolated_evaluation_reader(monkeypatch: Any) -> None:
    evaluation = _EvaluationConnection()
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: evaluation)
    headers = {"Authorization": f"Bearer {settings().admin_token}"}
    with TestClient(app) as client:
        response = client.get("/admin/research/model-comparisons?page=1&page_size=10", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "Stored comparison fixture"
    assert not {"body", "metrics", "checks"}.intersection(payload["items"][0])
    assert any("current_database()" in query for query in evaluation.statements)


def test_operations_snapshot_reads_migration_marker_without_schema_table_privilege() -> None:
    from woori.operations_dashboard import dashboard_snapshot

    class SnapshotConnection:
        def execute(self, query: str, _params: Any = None) -> _Cursor:
            if "payload->>'version'" in query:
                return _Cursor([{"version": 48}])
            if "codex.scheduled_local_file_probe.confirmed" in query:
                return _Cursor([{"count": 0, "last_at": None}])
            if "SELECT a.event_type,a.created_at" in query:
                return _Cursor([])
            if "to_regclass('public.trend_collection_runs')" in query:
                return _Cursor([{"available": False}])
            if "GROUP BY b.language_code" in query:
                return _Cursor([])
            if "FROM publishing_records r JOIN blogger_blogs b" in query:
                return _Cursor([])
            if "count(*)::int AS count FROM publishing_records" in query:
                return _Cursor([{"count": 0}])
            if "FROM article_quality_evaluations WHERE publish_ready=true" in query:
                return _Cursor([{"count": 0}])
            if "max(published_at)" in query:
                return _Cursor([{"at": None}])
            if "scope_type='global'" in query:
                return _Cursor([{"scope_type": "global", "scope_key": "", "configured_mode": "manual",
                                 "emergency_stopped": False, "daily_auto_limit": 1}])
            return _Cursor([])

    result = dashboard_snapshot(SnapshotConnection())
    assert result["schema_version"] == 48
    assert result["readiness"]["decision"] == "READY FOR OBSERVATION ONLY"
    assert result["readiness"]["limits"]["global_daily"] == 50
    assert result["readiness"]["modes"][-1]["status"] == "blocked"
    assert result["monitoring"]["alert_delivery_configured"] is False


def test_legacy_manuscript_detail_is_read_only_and_sanitized(monkeypatch: Any) -> None:
    evaluation_id, content_version_id = uuid4(), uuid4()
    monkeypatch.setattr(
        research_routes,
        "_read_manuscript_detail",
        lambda *_: {
            "id": evaluation_id,
            "content_version_id": content_version_id,
            "topic_key": "phase4l:legacy",
            "human_review_required": True,
            "publish_ready": False,
            "saved_body": "<script>alert(1)</script><p>근거 기반 원고</p>",
            "sources": [],
            "facts": [],
        },
    )

    @contextmanager
    def operations() -> Iterator[_OperationsConnection]:
        yield _OperationsConnection()

    monkeypatch.setattr(research_routes, "connection", operations)
    headers = {"Authorization": f"Bearer {settings().admin_token}"}
    with TestClient(app) as client:
        response = client.get(
            f"/admin/research/manuscripts/{evaluation_id}/{content_version_id}",
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_actions_allowed"] is False
    assert payload["publish_ready"] is False
    assert "<script" not in payload["safe_body_html"].lower()
    assert "근거 기반 원고" in payload["safe_body_html"]
