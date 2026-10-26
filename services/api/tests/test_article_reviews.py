from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Self
from uuid import uuid4

import pytest


def make_request(**overrides: Any) -> Any:
    from woori.research_routes import ArticleHumanReview

    values = {
        "evaluation_id": uuid4(),
        "content_version_id": uuid4(),
        "idempotency_key": "review-key-00000001",
        "reviewer_name": "Human reviewer",
        "factual_accuracy": "uncertain",
        "translation_naturalness": "not_assessed",
        "reader_value": "not_assessed",
        "disposition": "revision_requested",
        "comments": "Please verify the main claim against the source.",
        "requested_changes": "Clarify the date and cite the related fact.",
    }
    values.update(overrides)
    return ArticleHumanReview(**values)


def test_revision_request_requires_concrete_change_details() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="revision_requested_requires_change_details"):
        make_request(requested_changes=" ")
    assert make_request(disposition="reviewed", requested_changes="").disposition == "reviewed"


def test_editorial_approval_requires_positive_human_assessments() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="editorial_approval_requires_all_positive_review_checks"):
        make_request(disposition="approved")
    approved = make_request(
        disposition="approved", factual_accuracy="verified",
        translation_naturalness="acceptable", reader_value="useful",
    )
    assert approved.disposition == "approved"


def test_human_review_appends_note_without_approving_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    from woori import config, research_routes

    request = make_request(
        disposition="approved", factual_accuracy="verified",
        translation_naturalness="acceptable", reader_value="useful",
    )
    inserted = {
        "id": uuid4(),
        "evaluation_id": request.evaluation_id,
        "content_version_id": request.content_version_id,
        "idempotency_key": request.idempotency_key,
        "reviewer_name": request.reviewer_name,
        "disposition": request.disposition,
        "publish_ready": False,
    }
    statements: list[str] = []

    class EvalConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, _params: Any = None) -> Any:
            if "current_database" in sql:
                return SimpleNamespace(fetchone=lambda: {"name": "woori_blog_agent_eval"})
            return SimpleNamespace(fetchone=lambda: {"ok": 1})

    class OpsConnection:
        def execute(self, sql: str, _params: Any = None) -> Any:
            statements.append(sql)
            if "SELECT * FROM article_human_reviews WHERE idempotency_key" in sql:
                return SimpleNamespace(fetchone=lambda: None)
            if "INSERT INTO article_human_reviews" in sql:
                return SimpleNamespace(fetchone=lambda: inserted)
            return SimpleNamespace(fetchone=lambda: None)

    @contextmanager
    def ops_connection() -> Any:
        yield OpsConnection()

    monkeypatch.setattr(config, "settings", lambda: SimpleNamespace(evaluation_database_url="read-only-evaluation-dsn"))
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: EvalConnection())
    monkeypatch.setattr(research_routes, "connection", ops_connection)

    result = research_routes.record_article_review(request)

    assert result["publication_approval_granted"] is False
    assert result["publish_ready"] is False
    assert result["content_version_changed"] is False
    assert any("INSERT INTO article_human_reviews" in sql for sql in statements)
    assert any("INSERT INTO audit_events" in sql for sql in statements)
    assert not any("UPDATE content_versions" in sql or "UPDATE article_quality_evaluations" in sql for sql in statements)


def test_review_rejects_non_fed_or_unverified_targets_before_ops_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    from fastapi import HTTPException
    from woori import config, research_routes

    class EvalConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, _params: Any = None) -> Any:
            if "current_database" in sql:
                return SimpleNamespace(fetchone=lambda: {"name": "woori_blog_agent_eval"})
            return SimpleNamespace(fetchone=lambda: None)

    monkeypatch.setattr(config, "settings", lambda: SimpleNamespace(evaluation_database_url="read-only-evaluation-dsn"))
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: EvalConnection())
    monkeypatch.setattr(research_routes, "connection", lambda: pytest.fail("must not write an invalid review"))

    with pytest.raises(HTTPException) as error:
        research_routes.record_article_review(make_request())
    assert error.value.status_code == 404
