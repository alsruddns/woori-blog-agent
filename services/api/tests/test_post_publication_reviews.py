from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from woori.config import settings
from woori.main import app
from woori.publications import (
    ManualLiveRequestInput,
    PostPublicationReviewItemInput,
    PostPublicationReviewUpdate,
)


def test_post_publication_review_migration_is_additive_and_schema_56() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/053_post_publication_review.sql").read_text(encoding="utf-8").casefold()
    identity_migration = (root / "scripts/054_post_publication_content_identity.sql").read_text(encoding="utf-8").casefold()
    prepublication_migration = (root / "scripts/055_scheduled_prepublication_reviews.sql").read_text(encoding="utf-8").casefold()
    manual_migration = (root / "scripts/056_manual_publication_approval.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    provisioner = (root / "scripts/provision-test-database.py").read_text(encoding="utf-8")
    assert "references publishing_records(id)" in migration
    assert "drop table" not in migration and "delete from" not in migration
    assert "insert into schema_migrations(version) values(53)" in migration
    assert "add column content_id text" in identity_migration
    assert "insert into schema_migrations(version) values(54)" in identity_migration
    assert "MAX_SUPPORTED_SCHEMA_VERSION = 56" in runner
    assert "053_post_publication_review.sql" in runner
    assert "054_post_publication_content_identity.sql" in runner
    assert "055_scheduled_prepublication_reviews.sql" in runner
    assert "add column publishing_job_id uuid references publishing_jobs(id)" in prepublication_migration
    assert "prepublication_review_requires_active_scheduled_job" in prepublication_migration
    assert "before insert or update on post_publication_reviews" in prepublication_migration
    assert "insert into schema_migrations(version) values(55)" in prepublication_migration
    assert '(55, "scheduled_prepublication_reviews")' in provisioner
    assert "create table manual_publication_approval_events" in manual_migration
    assert "references publishing_jobs(id)" in manual_migration
    assert "before update or delete or truncate" in manual_migration
    assert "publication_lane in ('scheduled_auto','manual')" in manual_migration
    assert "prepublication_review_requires_manual_user_confirmation" in manual_migration
    assert "insert into schema_migrations(version) values(56)" in manual_migration
    assert '(56, "manual_publication_approval")' in provisioner


def test_review_input_types_are_bounded_and_explicit() -> None:
    valid = PostPublicationReviewItemInput(
        issue_type="source", severity="low", description="Recheck the linked source date.",
        idempotency_key="post-review-test-0001",
    )
    assert valid.issue_type == "source"
    with pytest.raises(ValidationError):
        PostPublicationReviewItemInput(
            issue_type="unknown", severity="low", description="note",
            idempotency_key="post-review-test-0002",
        )
    with pytest.raises(ValidationError):
        PostPublicationReviewUpdate(review_status="approved", review_notes="")


def test_manual_publication_requires_exact_payload_attestations_and_confirmation() -> None:
    values = {
        "content_version_id": "b6acaa88-d0a5-45e7-ad37-61f963a89231",
        "blog_id": "9245cb77-03bd-4fd6-a5f0-ea21f58232d0",
        "expected_title_sha256": "a" * 64,
        "expected_body_sha256": "b" * 64,
        "expected_html_sha256": "c" * 64,
        "actor_label": "Dashboard operator",
        "reason": "I reviewed this exact manuscript and target blog.",
        "reviewed_exact_content": True,
        "assertions_safe_to_publish": True,
        "rights_privacy_harm_checked": True,
        "confirmation": "PUBLISH THIS EXACT MANUSCRIPT PUBLICLY",
        "idempotency_key": "manual-publish-content-version-0001",
    }
    assert ManualLiveRequestInput(**values).reviewed_exact_content is True
    for field, value in (
        ("reviewed_exact_content", False),
        ("assertions_safe_to_publish", False),
        ("rights_privacy_harm_checked", False),
        ("confirmation", "PUBLISH"),
    ):
        with pytest.raises(ValidationError):
            ManualLiveRequestInput(**{**values, field: value})


def test_manual_live_route_keeps_quality_gaps_as_followups_and_has_no_write_call() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "services/api/woori/publications.py").read_text(encoding="utf-8")
    snapshot = source[source.index("def _manual_publication_snapshot"):source.index("def _manual_publication_blockers")]
    blockers = source[source.index("def _manual_publication_blockers"):source.index('@router.get("")')]
    request = source[source.index('@router.post("/manual-live-requests"'):source.index('@router.post("/scheduled-auto/verify-connections")')]
    assert 'followup("source"' in snapshot
    assert 'followup("copyright"' in snapshot
    assert "machine_passed" not in blockers and "publish_ready" not in blockers
    assert "manual_codex_import_origin_required" in snapshot
    assert "expected_html_sha256" in request
    assert "manual_publication_approval_events" in request
    assert "ORDER BY j.updated_at DESC" in request
    assert "blogger_zero_cost_policy_required" in blockers
    assert "publication_policy_missing" in blockers
    assert "policy_active" not in blockers
    assert "BloggerLivePublisher" not in request
    assert '"public_write_performed": False' in request


def test_api_only_joins_remote_verified_scheduled_publications() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "services/api/woori/publications.py").read_text(encoding="utf-8")
    assert "@router.get(\"/post-publication-reviews\")" in source
    assert "p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL" in source
    assert "j.publication_lane IN ('scheduled_auto','manual')" in source
    assert "publication.post_review_item.resolved" in source
    worker = (root / "services/api/woori/publication_worker.py").read_text(encoding="utf-8")
    assert 'if lane == "scheduled_auto":' in worker
    assert "post_publication_reviews(publishing_record_id" in worker
    assert "SET publishing_record_id=%s,post_id=%s,updated_at=now()" in worker


def test_dashboard_proxy_limits_post_review_routes() -> None:
    root = Path(__file__).resolve().parents[3]
    proxy = (root / "apps/dashboard/app/api/publications/[[...path]]/route.ts").read_text(encoding="utf-8")
    assert 'route === "post-publication-reviews"' in proxy
    assert 'export const PATCH = proxy' in proxy
    assert "post-publication-reviews\\/[a-f0-9-]+\\/items" in proxy


def test_post_publication_review_api_reads_isolated_schema_without_fake_posts() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/admin/publications/post-publication-reviews?status=all",
            headers={"Authorization": "Bearer " + settings().admin_token},
        )
    assert response.status_code == 200, response.text
    assert response.json()["verified_live_only"] is True
    assert response.json()["total"] == 0
