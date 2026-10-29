from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from woori.config import settings
from woori.main import app
from woori.publications import PostPublicationReviewItemInput, PostPublicationReviewUpdate


def test_post_publication_review_migration_is_additive_and_schema_55() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/053_post_publication_review.sql").read_text(encoding="utf-8").casefold()
    identity_migration = (root / "scripts/054_post_publication_content_identity.sql").read_text(encoding="utf-8").casefold()
    prepublication_migration = (root / "scripts/055_scheduled_prepublication_reviews.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    provisioner = (root / "scripts/provision-test-database.py").read_text(encoding="utf-8")
    assert "references publishing_records(id)" in migration
    assert "drop table" not in migration and "delete from" not in migration
    assert "insert into schema_migrations(version) values(53)" in migration
    assert "add column content_id text" in identity_migration
    assert "insert into schema_migrations(version) values(54)" in identity_migration
    assert "MAX_SUPPORTED_SCHEMA_VERSION = 55" in runner
    assert "053_post_publication_review.sql" in runner
    assert "054_post_publication_content_identity.sql" in runner
    assert "055_scheduled_prepublication_reviews.sql" in runner
    assert "add column publishing_job_id uuid references publishing_jobs(id)" in prepublication_migration
    assert "prepublication_review_requires_active_scheduled_job" in prepublication_migration
    assert "before insert or update on post_publication_reviews" in prepublication_migration
    assert "insert into schema_migrations(version) values(55)" in prepublication_migration
    assert '(55, "scheduled_prepublication_reviews")' in provisioner


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


def test_api_only_joins_remote_verified_scheduled_publications() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "services/api/woori/publications.py").read_text(encoding="utf-8")
    assert "@router.get(\"/post-publication-reviews\")" in source
    assert "p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL" in source
    assert "j.publication_lane='scheduled_auto'" in source
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
