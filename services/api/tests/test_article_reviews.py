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
                return SimpleNamespace(fetchone=lambda: {"name": "woori_blog_agent_eval", "role_name": "woori_eval_reader"})
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
                return SimpleNamespace(fetchone=lambda: {"name": "woori_blog_agent_eval", "role_name": "woori_eval_reader"})
            return SimpleNamespace(fetchone=lambda: None)

    monkeypatch.setattr(config, "settings", lambda: SimpleNamespace(evaluation_database_url="read-only-evaluation-dsn"))
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: EvalConnection())
    monkeypatch.setattr(research_routes, "connection", lambda: pytest.fail("must not write an invalid review"))

    with pytest.raises(HTTPException) as error:
        research_routes.record_article_review(make_request())
    assert error.value.status_code == 404


def test_editorial_status_uses_append_only_events_and_review_disposition() -> None:
    from datetime import UTC, datetime, timedelta

    from woori.research_routes import _editorial_status

    now = datetime.now(UTC)
    assert _editorial_status(None, None) == "unreviewed"
    assert _editorial_status({"created_at": now}, None) == "in_review"
    assert _editorial_status(
        {"created_at": now + timedelta(seconds=1)},
        {"created_at": now, "disposition": "reviewed"},
    ) == "in_review"
    assert _editorial_status(
        None, {"created_at": now, "disposition": "revision_requested"}
    ) == "revision_needed"
    assert _editorial_status(
        None, {"created_at": now, "disposition": "approved"}
    ) == "editorial_review_passed"


def test_editorial_revision_rechecks_quality_and_appends_without_changing_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from uuid import uuid4

    from woori import research_routes

    evaluation_id, version_id, revision_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    source = {
        "id": "source-1", "source_name": "Federal Reserve Board",
        "url": "https://www.federalreserve.gov/test.htm",
        "evidence": "The Federal Reserve Board issued a notice about its official review process for readers.",
        "rights": "Official source; cite the Board.",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    monkeypatch.setattr(research_routes, "_evaluation_article", lambda *_: {
        "source_ids": ["source-1"], "language_code": "en", "facts": [{}], "sources": [source],
    })
    statements: list[str] = []

    class FakeConnection:
        def execute(self, sql: str, _params: Any = None) -> Any:
            statements.append(sql)
            if "SELECT * FROM article_editorial_versions" in sql:
                return SimpleNamespace(fetchone=lambda: None)
            if "max(revision_number)" in sql:
                return SimpleNamespace(fetchone=lambda: {"next": 1})
            if "INSERT INTO article_editorial_versions" in sql:
                return SimpleNamespace(fetchone=lambda: {
                    "id": revision_id, "evaluation_id": evaluation_id,
                    "base_content_version_id": version_id, "revision_number": 1,
                    "machine_passed": True, "quality_status": "machine_checked_review_required",
                    "publish_ready": False,
                })
            if "INSERT INTO article_review_events" in sql:
                return SimpleNamespace(fetchone=lambda: {"id": event_id})
            return SimpleNamespace(fetchone=lambda: None)

    @contextmanager
    def fake_connection() -> Any:
        yield FakeConnection()

    monkeypatch.setattr(research_routes, "connection", fake_connection)
    request = research_routes.ArticleEditorialRevision(
        evaluation_id=evaluation_id, content_version_id=version_id,
        idempotency_key="editor-revision-000001", reviewer_name="Human editor",
        reason="Clarify the source and improve the explanation.",
        title="Federal Reserve Board notice explained",
        summary="A sourced explanation of the official notice.",
        keywords=["Federal Reserve Board notice"],
        body=("## What the notice states\n\nThe Federal Reserve Board issued a notice about its official review process. [source:source-1]\n\n"
              "## How to read it\n\nReaders can use the linked notice to check its scope and wording. [source:source-1]\n\n"
              "## Limits\n\nThis summary covers only information in the cited notice. [source:source-1]"),
    )
    result = research_routes.save_article_revision(request)
    assert result["revision"]["machine_passed"] is True
    assert result["publish_ready"] is False
    assert result["content_version_changed"] is False
    assert any("INSERT INTO article_editorial_versions" in sql for sql in statements)
    assert any("INSERT INTO audit_events" in sql for sql in statements)
    assert not any("UPDATE content_versions" in sql or "UPDATE article_quality_evaluations" in sql for sql in statements)


def test_phase4m_migration_defines_append_only_review_history() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sql = (root / "scripts/029_editorial_versions_and_progress.sql").read_text(encoding="utf-8")
    assert "article_review_events_immutable" in sql
    assert "article_editorial_versions_immutable" in sql
    assert "GRANT SELECT,INSERT" in sql
    assert '"publish_ready_changes":false' in sql


def test_editorial_source_reader_rejects_non_readonly_evaluation_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    import psycopg
    from fastapi import HTTPException
    from woori import config, research_routes

    class EvalConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str, _params: Any = None) -> Any:
            return SimpleNamespace(fetchone=lambda: {
                "database_name": "woori_blog_agent_eval", "role_name": "woori_eval_migration",
            })

    monkeypatch.setattr(config, "settings", lambda: SimpleNamespace(evaluation_database_url="read-only-evaluation-dsn"))
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: EvalConnection())
    with pytest.raises(HTTPException) as error:
        research_routes._evaluation_article(uuid4(), uuid4())
    assert error.value.status_code == 503
