from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from woori import content_imports
from woori.config import settings
from woori.db import connection
from woori.editorial_taxonomy import (
    EDITORIAL_CATEGORIES,
    ISSUE_LABELS,
    language_candidates,
    suggested_labels,
)
from woori.main import app


def valid_item(**updates: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "schema_version": "1.0", "content_id": "codex-export-article-001",
        "event_group_id": "event-policy-2026-001", "research_package_id": "package-001",
        "parent_content_id": None, "relation": "original", "source_region": "US",
        "language_code": "en", "target_audiences": [{"language_code": "en", "target_region": "US",
            "reader_relevance_reason": "The documented policy directly affects readers in the United States."}],
        "title": "A complete evidence-linked manuscript title", "body_markdown": "## What changed\n\n" + ("A grounded explanation with source links and clear separation between verified facts and analysis. " * 3),
        "category": "policy", "google_trends_based": False, "source_ids": ["src-official-1"],
        "sources": [{"source_id": "src-official-1", "title": "Official policy notice",
            "organization": "Example Public Agency", "url": "https://example.gov/policy",
            "published_at": "2026-10-20T10:00:00Z", "observed_at": "2026-10-28T02:00:00Z",
            "language_code": "en", "source_type": "government", "rights_status": "quotation_review_required",
            "rights_note": "Quotation length and reuse terms need human review."}],
        "claims": [{"claim_id": "claim-effective-date", "claim": "The notice states an effective date for the rule.",
            "source_ids": ["src-official-1"], "evidence_excerpt": "The rule is scheduled to take effect on the stated date.",
            "verification_status": "source_span_verified", "factual_state": "planned"}],
        "fact_checked_at": "2026-10-28T02:00:00Z", "seo": {"search_intent": "Understand the policy change and effective date",
            "primary_terms": ["policy change"], "related_terms": ["effective date"],
            "seo_title": "What the policy change means", "search_description": "A source-linked explanation of the change, its effective date, scope, and unresolved details for readers.",
            "core_question": "What does this policy change?", "core_answer": "It describes the documented rule and its stated effective date."},
        "blogger_labels": [], "generation_method": "manual_codex_import", "model_name": "Codex UI session",
        "generated_at": "2026-10-28T02:00:00Z", "created_by": "Editorial desk",
    }
    item.update(updates)
    return item


def test_eight_editorial_categories_and_overlapping_deduplication_groups() -> None:
    assert {item["slug"] for item in EDITORIAL_CATEGORIES} == {
        "economy", "finance", "stocks", "crypto", "technology", "semiconductors",
        "artificial-intelligence", "policy",
    }
    categories = {item["slug"]: item for item in EDITORIAL_CATEGORIES}
    assert categories["finance"]["deduplication_group"] == categories["stocks"]["deduplication_group"]
    assert categories["technology"]["deduplication_group"] == categories["semiconductors"]["deduplication_group"]


def test_country_is_context_only_and_multi_locale_needs_reader_rationale() -> None:
    result = language_candidates("US", {"en": "The US regulatory filing changes this reader's obligations."})
    assert result["suggested_languages"] == ["en"]
    assert result["publication_authorized"] is False
    tw = language_candidates("TW", {"zh-CN": "The topic has verified relevance to mainland Chinese readers."})
    assert tw["regional_note"] == "region_alone_does_not_select_simplified_chinese"
    assert tw["suggested_languages"] == ["zh-CN"]


def test_import_rejects_html_bad_urls_unlinked_claims_and_wrong_trends_label() -> None:
    valid = content_imports.ContentImport.model_validate(valid_item())
    assert valid.category == "policy"
    with pytest.raises(ValidationError, match="raw_html"):
        content_imports.ContentImport.model_validate(valid_item(body_markdown="## Heading\n\n" + "body " * 30 + "<script>alert(1)</script>"))
    bad_url = valid_item()
    bad_url["sources"][0]["url"] = "http://example.gov/policy"
    with pytest.raises(ValidationError):
        content_imports.ContentImport.model_validate(bad_url)
    bad_claim = valid_item()
    bad_claim["claims"][0]["source_ids"] = ["missing-source"]
    with pytest.raises(ValidationError, match="claim_references_unknown_source"):
        content_imports.ContentImport.model_validate(bad_claim)
    trends = valid_item(google_trends_based=True)
    with pytest.raises(ValidationError):
        content_imports.ContentImport.model_validate(trends)
    trends["blogger_labels"] = [ISSUE_LABELS["en"]]
    assert content_imports.ContentImport.model_validate(trends)


def test_region_issue_and_category_labels_are_deterministic() -> None:
    assert suggested_labels("policy", "ko", google_trends_based=True) == ["이슈", "정치·정책"]
    assert suggested_labels("semiconductors", "ja", google_trends_based=True) == ["話題", "半導体"]
    assert suggested_labels("economy", "zh-CN", google_trends_based=False) == ["经济"]


def test_import_endpoint_is_admin_only_idempotent_and_always_review_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with connection() as conn, conn.transaction(force_rollback=True):
        @contextmanager
        def shared() -> Iterator[Any]:
            with conn.transaction():
                yield conn

        monkeypatch.setattr(content_imports, "connection", shared)
        headers = {"Authorization": "Bearer " + settings().admin_token}
        with TestClient(app) as client:
            submission = {"submitted_by": "Reviewer", "item": valid_item()}
            assert client.post("/admin/research/content-imports", json=submission).status_code == 401
            first = client.post("/admin/research/content-imports", headers=headers, json=submission)
            assert first.status_code == 201, first.text
            result = first.json()
            assert result["state"] == "awaiting_human_review"
            assert result["generation_ready"] is False and result["publish_ready"] is False
            assert result["provider_called"] is False and result["blogger_write_performed"] is False
            assert result["source_fetch_performed"] is False
            second = client.post("/admin/research/content-imports", headers=headers, json=submission)
            assert second.status_code == 201 and second.json()["duplicate"] is True
            changed = valid_item(title="A different changed article title")
            conflict = client.post("/admin/research/content-imports", headers=headers,
                json={"submitted_by": "Reviewer", "item": changed})
            assert conflict.status_code == 409
            detail = client.get(f"/admin/research/content-imports/{result['import_id']}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["item"]["body_markdown"] == submission["item"]["body_markdown"].strip()
            assert detail.json()["publish_ready"] is False
            listed = client.get("/admin/research/content-imports", headers=headers)
            assert listed.status_code == 200
            assert any(item["id"] == result["import_id"] for item in listed.json()["items"])


def test_import_schema_and_migration_are_versioned_append_only_and_live_safe() -> None:
    root = Path(__file__).resolve().parents[3]
    schema = root / "docs/schemas/woori-content-import-1.0.schema.json"
    import json
    contract = json.loads(schema.read_text(encoding="utf-8"))
    assert contract["properties"]["schema_version"]["const"] == "1.0"
    migration = (root / "scripts/045_external_content_imports.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    provisioner = (root / "scripts/provision-test-database.py").read_text(encoding="utf-8")
    assert "insert into schema_migrations(version) values(45)" in migration
    assert "external_content_import_immutable" in migration
    assert "external_content_import_event_immutable" in migration
    assert "check (publish_ready=false)" in migration
    assert all(f"('{slug}')" in migration for slug in (
        "economy", "finance", "stocks", "crypto", "technology",
        "semiconductors", "artificial-intelligence", "policy",
    ))
    assert "045_external_content_imports.sql" in runner and '45, "external_content_imports"' in provisioner
    assert "drop table" not in migration and "delete from" not in migration
