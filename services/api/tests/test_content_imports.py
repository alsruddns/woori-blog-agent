from __future__ import annotations

import json
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


def reviewable_item() -> dict[str, Any]:
    evidence = (
        "The Official Agency published a policy notice describing a change to reporting requirements. "
        "The notice states that the policy is planned to take effect on 2026-11-01. "
        "The agency says organizations can use its reporting schedule to prepare for the stated date."
    )
    item = valid_item(
        content_id="reviewable-import-article-001",
        title="Official Agency policy change and reporting schedule",
        body_markdown=(
            "## What the notice says\n\nThe Official Agency notice describes a policy change to reporting requirements and states the planned effective date as 2026-11-01. [source:src-official-1]\n\n"
            "## Why the schedule matters\n\nOrganizations can use the agency reporting schedule to prepare for the stated date, while checking the published notice for the exact requirements. [source:src-official-1]\n\n"
            "## What readers should follow\n\nThe Official Agency notice is the reference for any later implementation details, so readers should compare updates with the published schedule. [source:src-official-1]"
        ),
        sources=[{"source_id": "src-official-1", "title": "Official Agency reporting notice",
            "organization": "Official Agency", "url": "https://example.gov/policy",
            "published_at": "2026-10-20T10:00:00Z", "observed_at": "2026-10-28T02:00:00Z",
            "language_code": "en", "source_type": "government", "rights_status": "public_domain",
            "rights_note": "Official material is listed as public domain; a human reviewer must confirm terms."}],
        claims=[{"claim_id": "claim-effective-date", "claim": "The policy is planned to take effect on 2026-11-01.",
            "source_ids": ["src-official-1"], "evidence_excerpt": evidence,
            "verification_status": "unverified", "factual_state": "planned"}],
        seo={"search_intent": "Understand the reporting policy change", "primary_terms": ["reporting policy"],
            "related_terms": ["effective date"], "seo_title": "Official Agency policy change and reporting schedule",
            "search_description": "What the Official Agency notice says about the planned reporting policy change, its effective date, and how organizations can follow the published schedule.",
            "core_question": "What does the reporting policy notice say?",
            "core_answer": "It describes a reporting requirement change and gives a planned effective date."},
    )
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
            assert result["content_version_id"]
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
            assert detail.json()["latest_version"]["content_version_id"] == result["content_version_id"]
            linked = conn.execute("SELECT title,body FROM content_versions WHERE id=%s", (result["content_version_id"],)).fetchone()
            assert linked and linked["title"] == submission["item"]["title"]
            listed = client.get("/admin/research/content-imports", headers=headers)
            assert listed.status_code == 200
            assert any(item["id"] == result["import_id"] for item in listed.json()["items"])


def test_p5_codex_021_fed_article_isolated_import_assessment_and_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = Path(__file__).resolve().parents[3] / "docs" / "development" / "P5-CODEX-021-article-ko.json"
    item = json.loads(artifact.read_text(encoding="utf-8"))
    validated = content_imports.ContentImport.model_validate(item)
    assert validated.research_package_id == "c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d"
    assert validated.generation_method == "manual_codex_import"
    assert validated.language_code == "ko"
    with connection() as conn, conn.transaction(force_rollback=True):
        @contextmanager
        def shared() -> Iterator[Any]:
            with conn.transaction():
                yield conn

        monkeypatch.setattr(content_imports, "connection", shared)
        headers = {"Authorization": "Bearer " + settings().admin_token}
        with TestClient(app) as client:
            submitted = client.post("/admin/research/content-imports", headers=headers,
                json={"submitted_by": "P5-CODEX-021 manual Codex import", "item": item})
            assert submitted.status_code == 201, submitted.text
            receipt = submitted.json()
            assert receipt["state"] == "awaiting_human_review"
            assert receipt["publish_ready"] is False
            assert receipt["provider_called"] is False
            assert receipt["blogger_write_performed"] is False
            assert receipt["content_version_id"]
            with content_imports.connection() as conn:
                conn.execute(
                    "INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                    ("research.source.live_document_verified", content_imports.Jsonb({
                        "import_id": receipt["import_id"],
                        "source_id": "fed-fomc-20261028",
                        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm",
                        "source_host": "www.federalreserve.gov",
                        "http_status": 200,
                        "checked_at": "2026-10-29T13:30:00+09:00",
                        "verified_claim_evidence": ["The Federal Reserve issued its official statement."],
                        "independent_source_count": 0,
                        "rights_approved": False,
                    })),
                )
            assessment = client.post(
                f"/admin/research/content-imports/{receipt['import_id']}/assessment",
                headers=headers, json={},
            )
            assert assessment.status_code == 201, assessment.text
            result = assessment.json()
            assert result["version_id"]
            assert result["publish_ready"] is False
            assert result["independent_source_verification"] is False
            assert next(check for check in result["seo_checks"] if check["key"] == "official_source_status")["status"] == "ready"
            assert "[source:" not in result["safe_html"].casefold()
            assert "FOMC" in result["safe_html"]
            assert result["safe_html"].startswith('<article class="wb-article"><p>')
            assert not any(token in result["safe_html"].casefold() for token in ("<script", "<iframe", "onerror="))
            detail = client.get(f"/admin/research/content-imports/{receipt['import_id']}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["source_verifications"][0]["payload"]["source_id"] == "fed-fomc-20261028"
            assert detail.json()["latest_version"]["content_version_id"] == receipt["content_version_id"]
            assert len(detail.json()["assessments"]) == 1


def test_scheduled_origin_audit_requires_registered_blog_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with connection() as conn, conn.transaction(force_rollback=True):
        @contextmanager
        def shared() -> Iterator[Any]:
            with conn.transaction():
                yield conn

        monkeypatch.setattr(content_imports, "connection", shared)
        blog = conn.execute(
            "SELECT id,url,language_code FROM blogger_blogs WHERE language_code='ko' ORDER BY url LIMIT 1"
        ).fetchone()
        assert blog
        blog_id = "9876543210123456789"
        conn.execute("UPDATE blogger_blogs SET blog_id=%s,active=true WHERE id=%s", (blog_id, blog["id"]))
        headers = {"Authorization": "Bearer " + settings().admin_token}
        item = valid_item(
            content_id="scheduled-audit-test-001", generation_method="chatgpt_scheduled_export",
            language_code="ko", target_audiences=[{"language_code": "ko", "target_region": "KR",
                "reader_relevance_reason": "The scheduled market review is written for Korean readers."}],
        )
        with TestClient(app) as client:
            submitted = client.post("/admin/research/content-imports", headers=headers,
                                   json={"submitted_by": "Scheduled test", "item": item})
            assert submitted.status_code == 201, submitted.text
            import_id = submitted.json()["import_id"]
            origin = {
                "task_type": "market_close_kr", "task_id": "woori-market-close-kr",
                "occurrence_id": "woori-market-close-kr-20261028-01",
                "executed_at": "2026-10-28T08:06:00Z", "market_date": "2026-10-28",
                "target_language_code": "ko", "target_blog_id": blog_id,
                "target_blog_url": blog["url"], "source_as_of": "2026-10-28T08:00:00Z",
            }
            path = f"/admin/research/content-imports/{import_id}/scheduled-origin"
            assert client.post(path, json=origin).status_code == 401
            first = client.post(path, headers=headers, json=origin)
            assert first.status_code == 201, first.text
            assert first.json()["provenance_verified"] is False
            assert first.json()["auto_publication_enabled"] is False
            second = client.post(path, headers=headers, json=origin)
            assert second.status_code == 201 and second.json()["duplicate"] is True
            changed = dict(origin, source_as_of="2026-10-28T08:01:00Z")
            conflict = client.post(path, headers=headers, json=changed)
            assert conflict.status_code == 409
            second_item = dict(item, content_id="scheduled-audit-test-002")
            second_import = client.post("/admin/research/content-imports", headers=headers,
                                        json={"submitted_by": "Scheduled test", "item": second_item})
            assert second_import.status_code == 201, second_import.text
            reused_occurrence = client.post(
                f"/admin/research/content-imports/{second_import.json()['import_id']}/scheduled-origin",
                headers=headers, json=origin,
            )
            assert reused_occurrence.status_code == 409
            audit = conn.execute(
                "SELECT payload FROM audit_events WHERE event_type='content.import.scheduled_origin_recorded'"
            ).fetchall()
            assert len(audit) == 1
            assert audit[0]["payload"]["provenance_self_reported"] is True
            assert audit[0]["payload"]["publish_ready"] is False


def test_import_assessment_versions_review_localization_and_mock_are_fail_closed(
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
            submitted = client.post("/admin/research/content-imports", headers=headers,
                json={"submitted_by": "Reviewer", "item": valid_item()})
            assert submitted.status_code == 201, submitted.text
            import_id = submitted.json()["import_id"]
            detail = client.get(f"/admin/research/content-imports/{import_id}", headers=headers).json()
            first = detail["latest_version"]
            assert first["version_number"] == 1

            assessment = client.post(f"/admin/research/content-imports/{import_id}/assessment",
                headers=headers, json={"version_id": first["id"]})
            assert assessment.status_code == 201, assessment.text
            assessed = assessment.json()
            assert assessed["publish_ready"] is False and assessed["generation_ready"] is False
            assert assessed["independent_source_verification"] is False
            assert "<script" not in assessed["safe_html"].casefold()

            version_request = {"base_version_id": first["id"], "title": "A clearer imported manuscript title",
                "body_markdown": "## Main point\n\n" + ("A revised source-linked explanation that keeps the reader context clear. [source:src-official-1]\n\n" * 2),
                "seo_metadata": valid_item()["seo"], "blogger_labels": [], "author_label": "Editor",
                "reason": "Clarify the first paragraph and source note"}
            edited = client.post(f"/admin/research/content-imports/{import_id}/versions", headers=headers, json=version_request)
            assert edited.status_code == 201, edited.text
            second = edited.json()
            assert second["version_number"] == 2 and second["publish_ready"] is False
            assert second["content_version_id"]
            assert second["content_version_id"] != first["content_version_id"]
            conflict = client.post(f"/admin/research/content-imports/{import_id}/versions", headers=headers, json=version_request)
            assert conflict.status_code == 409
            stale = dict(version_request, base_version_id=first["id"], title="Stale edit should not replace a newer version")
            assert client.post(f"/admin/research/content-imports/{import_id}/versions", headers=headers, json=stale).status_code == 409

            start = client.post(f"/admin/research/content-imports/{import_id}/reviews", headers=headers,
                json={"version_id": second["version_id"], "disposition": "review_started", "reviewer_label": "Editor",
                    "reason": "Begin source and rights review"})
            assert start.status_code == 201
            denied_pass = client.post(f"/admin/research/content-imports/{import_id}/reviews", headers=headers,
                json={"version_id": second["version_id"], "disposition": "editorial_review_passed", "reviewer_label": "Editor",
                    "reason": "Attempt without reviewed documents", "sources_examined": True,
                    "claims_checked": True, "rights_reviewed": True})
            # The fixture deliberately fails a deterministic gate; human affirmations cannot override it.
            assert denied_pass.status_code == 409
            mock = client.post(f"/admin/research/content-imports/{import_id}/mock-publications", headers=headers,
                json={"version_id": second["version_id"], "idempotency_key": "import-test-mock-001",
                    "scenario": "success", "requested_by": "Editor"})
            assert mock.status_code == 409

            localization = client.post(f"/admin/research/content-imports/{import_id}/localizations", headers=headers,
                json={"target_language": "ko", "requester_label": "Editor", "reason": "Prepare a Korean edition for review"})
            assert localization.status_code == 201
            assert localization.json()["status"] == "awaiting_external_provider"
            assert localization.json()["generation_provider_available"] is False
            cancellation = client.post(
                f"/admin/research/content-imports/{import_id}/localizations/ko/cancel", headers=headers,
                json={"requester_label": "Editor", "reason": "Cancel the Korean localization request"},
            )
            assert cancellation.status_code == 201 and cancellation.json()["status"] == "cancelled"
            localized_item = valid_item(content_id="localized-article-001", relation="localized",
                parent_content_id="codex-export-article-001", language_code="ko",
                target_audiences=[{"language_code": "ko", "target_region": "KR", "reader_relevance_reason": "The documented policy directly affects readers in Korea."}])
            localized = client.post("/admin/research/content-imports", headers=headers,
                json={"submitted_by": "Reviewer", "item": localized_item})
            assert localized.status_code == 201, localized.text
            assert localized.json()["content_version_id"]
            repeated_language = client.post(f"/admin/research/content-imports/{import_id}/localizations", headers=headers,
                json={"target_language": "ko", "requester_label": "Editor", "reason": "Request a duplicate Korean edition"})
            assert repeated_language.status_code == 409
            final = client.get(f"/admin/research/content-imports/{import_id}", headers=headers).json()
            assert final["latest_version"]["id"] == second["version_id"]
            assert final["editorial_review_status"] == "review_started"
            assert final["publish_ready"] is False and final["generation_ready"] is False


def test_import_review_endpoints_fail_closed_until_migration_048(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        def __init__(self, row: dict[str, Any]) -> None:
            self.row = row

        def fetchone(self) -> dict[str, Any]:
            return self.row

    class OldSchemaConnection:
        def execute(self, query: str, params: Any = None) -> Result:
            if "to_regclass('public.external_content_import_content_links')" in query:
                return Result({"table_name": None})
            raise AssertionError("The old-schema guard must stop before reading import tables")

    old_schema = OldSchemaConnection()

    @contextmanager
    def shared() -> Iterator[Any]:
        yield old_schema

    monkeypatch.setattr(content_imports, "connection", shared)
    headers = {"Authorization": "Bearer " + settings().admin_token}
    with TestClient(app) as client:
        response = client.get("/admin/research/content-imports", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Content import manuscript bridge migration 048 is required"


def test_import_machine_review_then_fake_publisher_never_changes_live_readiness(
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
            created = client.post("/admin/research/content-imports", headers=headers,
                json={"submitted_by": "Review Desk", "item": reviewable_item()})
            assert created.status_code == 201, created.text
            import_id = created.json()["import_id"]
            version = client.get(f"/admin/research/content-imports/{import_id}", headers=headers).json()["latest_version"]
            assessed_response = client.post(f"/admin/research/content-imports/{import_id}/assessment", headers=headers,
                json={"version_id": version["id"]})
            assert assessed_response.status_code == 201, assessed_response.text
            assessment = assessed_response.json()
            assert assessment["machine_passed"] is True, assessment["machine_checks"]
            review = client.post(f"/admin/research/content-imports/{import_id}/reviews", headers=headers, json={
                "version_id": version["id"], "disposition": "editorial_review_passed", "reviewer_label": "Human editor",
                "reason": "Documents, claims, and reuse rights were checked directly by the reviewer.",
                "sources_examined": True, "claims_checked": True, "rights_reviewed": True})
            assert review.status_code == 201, review.text
            simulated = client.post(f"/admin/research/content-imports/{import_id}/mock-publications", headers=headers, json={
                "version_id": version["id"], "idempotency_key": "reviewable-import-mock-001",
                "scenario": "success", "requested_by": "Human editor"})
            assert simulated.status_code == 201, simulated.text
            result = simulated.json()
            assert result["simulation_only"] is True and result["external_network_calls"] == 0
            assert result["real_blog_mutated"] is False and result["publish_ready"] is False
            duplicate = client.post(f"/admin/research/content-imports/{import_id}/mock-publications", headers=headers, json={
                "version_id": version["id"], "idempotency_key": "reviewable-import-mock-001",
                "scenario": "success", "requested_by": "Human editor"})
            assert duplicate.status_code == 201 and duplicate.json()["duplicate"] is True


def test_import_schema_and_migration_are_versioned_append_only_and_live_safe() -> None:
    root = Path(__file__).resolve().parents[3]
    schema = root / "docs/schemas/woori-content-import-1.0.schema.json"
    import json
    contract = json.loads(schema.read_text(encoding="utf-8"))
    assert contract["required"] == ["submitted_by", "item"]
    assert contract["properties"]["item"]["properties"]["schema_version"]["const"] == "1.0"
    for sample in (root / "docs/schemas/examples").glob("content-import-*.example.json"):
        content_imports.ImportSubmission.model_validate(json.loads(sample.read_text(encoding="utf-8")))
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
    assert "045_external_content_imports.sql" in runner and "047_import_review_pipeline.sql" in runner
    assert "048_import_content_version_bridge.sql" in runner
    assert '45, "external_content_imports"' in provisioner and '47, "import_review_pipeline"' in provisioner
    assert '48, "import_content_version_bridge"' in provisioner
    assert "drop table" not in migration and "delete from" not in migration
    review_migration = (root / "scripts/047_import_review_pipeline.sql").read_text(encoding="utf-8").casefold()
    assert "check (generation_ready=false)" in review_migration and "check (publish_ready=false)" in review_migration
    assert "before update or delete or truncate" in review_migration
    bridge_migration = (root / "scripts/048_import_content_version_bridge.sql").read_text(encoding="utf-8").casefold()
    assert "external_content_import_content_links" in bridge_migration
    assert "content_versions" in bridge_migration and "before update or delete or truncate" in bridge_migration
    assert "insert into schema_migrations(version) values(48)" in bridge_migration
