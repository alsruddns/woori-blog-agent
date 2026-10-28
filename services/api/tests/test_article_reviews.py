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


def test_publication_approval_requires_explicit_version_and_revocation_reference() -> None:
    from pydantic import ValidationError
    from woori.research_routes import PublicationApproval

    values = {
        "evaluation_id": uuid4(), "content_version_id": uuid4(),
        "event_key": "publication-approval-key-01", "actor": "Site editor",
        "action": "approved", "reason": "Reviewed the latest machine-checked version.",
    }
    approval = PublicationApproval(**values)
    assert approval.editorial_version_id is None
    assert approval.action == "approved"
    with pytest.raises(ValidationError, match="revocation_must_reference_approval_event"):
        PublicationApproval(**{**values, "event_key": "publication-revoke-key-01", "action": "revoked"})


def test_publication_approval_is_bound_to_current_body_hash_and_revocation() -> None:
    from woori.research_routes import _publication_approval_status

    approved = [{"action": "approved", "body_sha256": "a" * 64}]
    assert _publication_approval_status(approved, "a" * 64) == "approved_for_exact_version"
    assert _publication_approval_status(approved, "b" * 64) == "approval_required"
    assert _publication_approval_status(
        [{"action": "revoked", "body_sha256": "a" * 64}], "a" * 64,
    ) == "revoked"


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
            if "FROM publishing_records" in sql:
                return SimpleNamespace(fetchall=list)
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


def test_phase5a_hash_migration_and_manuscript_list_keep_each_saved_version() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/032_editorial_base_hash.sql").read_text(encoding="utf-8")
    route = (root / "services/api/woori/research_routes.py").read_text(encoding="utf-8")
    assert "base_body_sha256 char(64)" in migration
    assert "article_editorial_base_body_sha256_format" in migration
    assert "INSERT INTO schema_migrations(version) VALUES(32)" in migration
    assert "DISTINCT ON (q.content_version_id)" in route


def test_editorial_html_allowlist_preserves_formatting_and_drops_active_content() -> None:
    from woori.editorial_html import sanitize_editorial_html

    safe, plain = sanitize_editorial_html(
        '<h2 onclick="run()">Facts</h2><p><strong>Verified</strong> [source:123]</p>'
        '<a href="javascript:alert(1)" onmouseover="run()">unsafe</a>'
        '<a href="https://example.gov/source">official source</a><script>alert(1)</script>'
    )
    assert "<h2>Facts</h2>" in safe
    assert "<strong>Verified</strong>" in safe
    assert "onclick" not in safe and "onmouseover" not in safe
    assert "javascript:" not in safe and "<script" not in safe and "alert(1)" not in safe
    assert 'href="https://example.gov/source" rel="nofollow noopener noreferrer"' in safe
    assert "[source:123]" in plain and "official source" in plain


def test_blogger_markdown_renderer_keeps_title_out_of_body_and_supports_editorial_blocks() -> None:
    from woori.editorial_html import markdown_to_blogger_html

    html = markdown_to_blogger_html(
        "---\nlanguage: ko\nlabels: [이슈]\n---\n"
        "# Taiwan pay proposal\n\n"
        "A **verified** lead with [an official source](https://example.gov/report).\n\n"
        "## Two different measures\n\n"
        "| Measure | Status |\n| --- | --- |\n| Allowance | Proposed |\n| General pay | Planned |\n\n"
        "> The payment status remains unverified.\n\n"
        "<script>alert(1)</script>",
        post_title="Taiwan pay proposal",
        summary="SEO metadata must not be injected into the article body.",
    )

    assert html.startswith('<article class="wb-article">')
    assert "<h1" not in html and "Taiwan pay proposal" not in html
    assert "<h2>Two different measures</h2>" in html
    assert '<div class="wb-table-wrap"><table>' in html
    assert '<th scope="col">Measure</th>' in html
    assert "<blockquote>The payment status remains unverified.</blockquote>" in html
    assert "<script" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "SEO metadata must not be injected" not in html


@pytest.mark.parametrize("locale", ["ko", "en"])
def test_codex_evaluation_articles_render_with_sources_and_without_duplicate_h1(locale: str) -> None:
    from pathlib import Path

    from woori.editorial_html import markdown_to_blogger_html

    root = Path(__file__).resolve().parents[3]
    path = root / "docs" / "development" / f"P5-CODEX-002-article-{locale}.md"
    article = path.read_text(encoding="utf-8")
    title = next(line.removeprefix("# ").strip() for line in article.splitlines() if line.startswith("# "))
    html = markdown_to_blogger_html(article, post_title=title)

    assert title not in html and "<h1" not in html
    assert "<h2>" in html and "https://" in html
    assert "FACT-F" not in html
    assert "blogger_submission" not in html and "evaluation_only" not in html

    from woori.editorial_seo import EditorialSeoMetadata
    from woori.research_routes import EditorialPreviewRequest, editorial_preview

    preview = editorial_preview(EditorialPreviewRequest(
        title=title,
        body=article,
        summary="",
        language_code=locale,
        seo_metadata=EditorialSeoMetadata(language_code=locale, seo_title=title),
    ))
    assert preview["language_code"] == locale
    assert preview["publication_performed"] is False
    assert "seo_checks" in preview and preview["rendered_sha256"]
    assert "FACT-F" not in preview["post_html"]
    assert title not in preview["post_html"]


def test_blogger_html_sanitizer_allows_only_safe_table_image_and_design_hooks() -> None:
    from woori.editorial_html import sanitize_editorial_html

    safe, _plain = sanitize_editorial_html(
        '<article class="wb-article" onclick="x()"><div class="wb-table-wrap">'
        '<table><thead><tr><th scope="col">Value</th></tr></thead><tbody><tr><td>10</td></tr></tbody></table></div>'
        '<figure class="wb-figure"><img src="https://example.gov/chart.png" alt="Budget chart" onerror="x()">'
        '<figcaption class="wb-caption">Official chart</figcaption></figure>'
        '<img src="javascript:alert(1)" alt="unsafe"><script>alert(1)</script></article>'
    )

    assert 'class="wb-article"' in safe and 'class="wb-table-wrap"' in safe
    assert '<th scope="col">Value</th>' in safe
    assert 'src="https://example.gov/chart.png" alt="Budget chart"' in safe
    assert 'class="wb-caption"' in safe
    assert "onclick" not in safe and "onerror" not in safe
    assert "javascript:" not in safe and "alert(1)" not in safe
    with pytest.raises(ValueError, match="editorial_html_unclosed_h1"):
        sanitize_editorial_html("<h1>Malformed title<p>body")


def test_trends_labels_are_locale_specific_and_only_applied_when_marked() -> None:
    from woori.editorial_html import resolve_blogger_labels

    assert resolve_blogger_labels("ko", True, ["finance"]) == ["이슈", "finance"]
    assert resolve_blogger_labels("en", True, []) == ["Issues"]
    assert resolve_blogger_labels("ja", True, []) == ["話題"]
    assert resolve_blogger_labels("zh-CN", True, []) == ["热点"]
    assert resolve_blogger_labels("ko", False, ["finance"]) == ["finance"]


def test_editorial_preview_is_sanitized_non_persistent_and_never_duplicates_post_title() -> None:
    from woori.research_routes import EditorialPreviewRequest, editorial_preview

    result = editorial_preview(EditorialPreviewRequest(
        title="A verified policy proposal",
        body="# A verified policy proposal\n\n## What changes\n\nA factual paragraph.",
        summary="A search-only summary.",
        language_code="en",
        google_trends_based=True,
        labels=["finance"],
    ))

    assert result["title"] == "A verified policy proposal"
    assert result["title_in_body"] is False
    assert result["publication_performed"] is False
    assert result["labels"] == ["Issues", "finance"]
    assert "<h1" not in result["post_html"] and "A verified policy proposal" not in result["post_html"]
    assert "A search-only summary." not in result["post_html"]

    html_result = editorial_preview(EditorialPreviewRequest(
        title="Same title", body="<h1>Same title</h1><p>Body remains visible.</p>",
        body_format="html", language_code="ko",
    ))
    assert "<h1" not in html_result["post_html"] and "Same title" not in html_result["post_html"]
    assert "Body remains visible." in html_result["post_html"]


def test_editorial_preview_returns_deterministic_seo_checks_without_predictive_score() -> None:
    from pathlib import Path

    from woori.editorial_seo import EditorialSeoMetadata, SearchConsoleSnapshot, SeoSource
    from woori.research_routes import EditorialPreviewRequest, editorial_preview

    request = EditorialPreviewRequest(
        title="Policy change: what readers should know",
        body="# Policy change: what readers should know\n\n## What changed\n\n"
        "The official proposal describes a scheduled adjustment. Read the [source](https://example.gov/policy).",
        summary="A concise explanation of the policy proposal and its verified status.",
        language_code="en",
        seo_metadata=EditorialSeoMetadata(
            language_code="en", search_intent="informational", primary_keyword="policy proposal",
            seo_title="Policy change: what readers should know",
            search_description="A concise explanation of the policy proposal and its verified status.",
            official_sources=[SeoSource(title="Official notice", url="https://example.gov/policy", official_status="unverified")],
        ),
    )
    first = editorial_preview(request)
    second = editorial_preview(request)
    assert first["post_html"] == second["post_html"]
    assert first["rendered_sha256"] == second["rendered_sha256"]
    assert first["renderer_version"] and first["design_system_version"]
    assert first["seo_metadata"]["target_region"] is None
    assert first["publication_performed"] is False
    check_map = {check["key"]: check for check in first["seo_checks"]}
    assert check_map["title_matches_article"]["status"] == "ready"
    assert check_map["search_intent"]["status"] == "ready"
    assert check_map["official_source_status"]["status"] == "review"
    assert check_map["duplicate_content"]["status"] == "not_measured"
    assert check_map["search_performance"]["status"] == "not_measured"
    assert "score" not in first

    snapshot = SearchConsoleSnapshot()
    assert snapshot.impressions is None and snapshot.clicks is None and snapshot.queries == []

    root = Path(__file__).resolve().parents[3]
    preview_css = (root / "apps/dashboard/public/blogger-editorial.css").read_text(encoding="utf-8")
    theme_css = (root / "docs/operations/blogger-editorial-theme.css").read_text(encoding="utf-8")
    assert preview_css == theme_css
    assert "--woori-article-body-size: 17px" in preview_css
    assert "--woori-article-body-leading: 1.8" in preview_css
    assert "--woori-article-width: 750px" in preview_css
    assert ".wb-article h2" in preview_css and ".wb-article h3" in preview_css


def test_seo_source_urls_are_https_only() -> None:
    from pydantic import ValidationError
    from woori.editorial_seo import SeoSource

    with pytest.raises(ValidationError, match="seo_source_url_must_be_https"):
        SeoSource(title="Unsafe", url="javascript:alert(1)")


def test_seo_readiness_flags_dropped_images_without_alt_text() -> None:
    from woori.editorial_seo import EditorialSeoMetadata
    from woori.research_routes import EditorialPreviewRequest, editorial_preview

    result = editorial_preview(EditorialPreviewRequest(
        title="Accessible report", body='<h2>Summary</h2><p>Verified data.</p><img src="https://example.gov/chart.png">',
        body_format="html", language_code="en",
        seo_metadata=EditorialSeoMetadata(language_code="en", seo_title="Accessible report"),
    ))
    image_check = next(item for item in result["seo_checks"] if item["key"] == "image_alt")
    assert image_check["status"] == "review"
    assert "대체 텍스트" in image_check["message"]
    assert "<img" not in result["post_html"]


def test_editorial_seo_migration_is_additive_and_keeps_append_only_revisions() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/041_editorial_seo_metadata.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    assert "add column seo_metadata jsonb not null default '{}'::jsonb" in migration
    assert "check (jsonb_typeof(seo_metadata) = 'object')" in migration
    assert "insert into schema_migrations(version) values(41)" in migration
    assert "040_research_package_review_state.sql" in runner
    assert "041_editorial_seo_metadata.sql" in runner
    assert "drop table" not in migration and "delete from" not in migration
    assert "update article_editorial_versions" not in migration


def test_editorial_revision_rejects_stale_base_without_inserting_a_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from fastapi import HTTPException
    from woori import article_quality, research_routes

    source = {
        "source_ids": ["source-1"], "language_code": "en", "facts": [{}], "saved_body": "Original draft",
        "sources": [{"id": "source-1", "source_name": "Federal Reserve Board",
            "url": "https://www.federalreserve.gov/test.htm",
            "evidence": "The Federal Reserve Board issued an official notice for readers.",
            "rights": "Official source; cite the Board.",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat()}],
    }
    latest_id = uuid4()
    statements: list[str] = []

    class FakeConnection:
        def execute(self, sql: str, _params: Any = None) -> Any:
            statements.append(sql)
            if "SELECT * FROM article_editorial_versions" in sql:
                return SimpleNamespace(fetchone=lambda: None)
            if "SELECT id,body_sha256 FROM article_editorial_versions" in sql:
                return SimpleNamespace(fetchone=lambda: {"id": latest_id, "body_sha256": "a" * 64})
            return SimpleNamespace(fetchone=lambda: None)

    @contextmanager
    def fake_connection() -> Any:
        yield FakeConnection()

    monkeypatch.setattr(research_routes, "_evaluation_article", lambda *_args: source)
    monkeypatch.setattr(article_quality, "evaluate", lambda *_args: {"checks": {}, "machine_passed": True})
    monkeypatch.setattr(research_routes, "connection", fake_connection)
    request = research_routes.ArticleEditorialRevision(
        evaluation_id=uuid4(), content_version_id=uuid4(), idempotency_key="stale-editor-000001",
        reviewer_name="Human editor", reason="Update from an older open browser tab.", title="Edited title",
        summary="A search description.", keywords=["Federal Reserve"],
        html_body="<p>The revised editorial body has enough content.</p>",
        base_editorial_version_id=None,
    )
    with pytest.raises(HTTPException) as error:
        research_routes.save_article_revision(request)
    assert error.value.status_code == 409
    assert not any("INSERT INTO article_editorial_versions" in statement for statement in statements)


def test_editorial_schedule_requires_future_timezone_and_labels_are_unique() -> None:
    from datetime import UTC, datetime, timedelta

    from pydantic import ValidationError
    from woori.research_routes import ArticleEditorialRevision

    base = {
        "evaluation_id": uuid4(), "content_version_id": uuid4(), "idempotency_key": "revision-fields-0001",
        "reviewer_name": "Human editor", "reason": "Improve the outline and source descriptions.",
        "title": "A verified title", "body": "Body", "summary": "Search description.",
        "keywords": ["verified topic"],
    }
    with pytest.raises(ValidationError, match="scheduled_editorial_requires_timezone_aware_future_date"):
        ArticleEditorialRevision(**base, publication_mode="scheduled")
    scheduled = ArticleEditorialRevision(
        **base, publication_mode="scheduled", planned_publish_at=datetime.now(UTC) + timedelta(days=1)
    )
    assert scheduled.publication_mode == "scheduled"
    with pytest.raises(ValidationError, match="blogger_labels_must_be_unique"):
        ArticleEditorialRevision(**base, blogger_labels=["Finance", " finance "])


def test_phase5a_migration_persists_editor_metadata_without_publication_permission() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sql = (root / "scripts/030_manuscript_editing_metadata.sql").read_text(encoding="utf-8")
    for column in ("html_body", "seo_description", "blogger_labels", "publication_mode",
                   "planned_publish_at", "target_blog_id", "base_editorial_version_id"):
        assert f"ADD COLUMN {column}" in sql
    assert '"publish_ready_changes":false' in sql
    link_sql = (root / "scripts/031_editorial_existing_post_link.sql").read_text(encoding="utf-8")
    assert "existing_remote_post_id" in link_sql
    assert '"live_writes_enabled":false' in link_sql


def test_published_editorial_revision_cannot_be_retargeted_to_another_blog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from fastapi import HTTPException
    from woori import article_quality, research_routes

    target_blog_id, original_blog_id = uuid4(), uuid4()
    source = {
        "source_ids": ["source-1"], "language_code": "en", "facts": [{}], "saved_body": "Original draft",
        "sources": [{"id": "source-1", "source_name": "Federal Reserve Board",
            "url": "https://www.federalreserve.gov/test.htm",
            "evidence": "The Federal Reserve Board issued an official notice for readers.",
            "rights": "Official source; cite the Board.",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat()}],
    }
    statements: list[str] = []

    class FakeConnection:
        def execute(self, sql: str, _params: Any = None) -> Any:
            statements.append(sql)
            if "SELECT * FROM article_editorial_versions" in sql:
                return SimpleNamespace(fetchone=lambda: None)
            if "SELECT id,body_sha256 FROM article_editorial_versions" in sql:
                return SimpleNamespace(fetchone=lambda: None)
            if "SELECT blog_id,remote_post_id FROM publishing_records" in sql:
                return SimpleNamespace(fetchall=lambda: [{"blog_id": original_blog_id, "remote_post_id": "real-post-id"}])
            if "SELECT id,language_code,active FROM blogger_blogs" in sql:
                return SimpleNamespace(fetchone=lambda: {"id": target_blog_id, "language_code": "en", "active": True})
            return SimpleNamespace(fetchone=lambda: None)

    @contextmanager
    def fake_connection() -> Any:
        yield FakeConnection()

    monkeypatch.setattr(research_routes, "_evaluation_article", lambda *_args: source)
    monkeypatch.setattr(article_quality, "evaluate", lambda *_args: {"checks": {}, "machine_passed": True})
    monkeypatch.setattr(research_routes, "connection", fake_connection)
    request = research_routes.ArticleEditorialRevision(
        evaluation_id=uuid4(), content_version_id=uuid4(), idempotency_key="retarget-editor-00001",
        reviewer_name="Human editor", reason="Change a published article target blog.", title="Edited title",
        summary="A search description.", keywords=["Federal Reserve"],
        html_body="<p>The revised body has enough readable content.</p>", target_blog_id=target_blog_id,
    )
    with pytest.raises(HTTPException) as error:
        research_routes.save_article_revision(request)
    assert error.value.status_code == 409
    assert not any("INSERT INTO article_editorial_versions" in statement for statement in statements)


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
