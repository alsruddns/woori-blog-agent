import asyncio
import json
import logging
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from woori.config import settings
from woori.main import app, database_error
from woori.publications import (
    ManualLiveRequestInput,
    PostPublicationReviewItemInput,
    PostPublicationReviewUpdate,
)


def test_post_publication_review_migration_is_additive_and_schema_59() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/053_post_publication_review.sql").read_text(encoding="utf-8").casefold()
    identity_migration = (root / "scripts/054_post_publication_content_identity.sql").read_text(encoding="utf-8").casefold()
    prepublication_migration = (root / "scripts/055_scheduled_prepublication_reviews.sql").read_text(encoding="utf-8").casefold()
    manual_migration = (root / "scripts/056_manual_publication_approval.sql").read_text(encoding="utf-8").casefold()
    reason_migration = (root / "scripts/057_manual_publication_reason_length.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    provisioner = (root / "scripts/provision-test-database.py").read_text(encoding="utf-8")
    assert "references publishing_records(id)" in migration
    assert "drop table" not in migration and "delete from" not in migration
    assert "insert into schema_migrations(version) values(53)" in migration
    assert "add column content_id text" in identity_migration
    assert "insert into schema_migrations(version) values(54)" in identity_migration
    assert "scripts/059_verified_publication_record_insert.sql" in runner
    permission = (root / 'scripts/059_verified_publication_record_insert.sql').read_text(encoding='utf-8').casefold()
    assert 'grant insert on publishing_records' in permission
    assert 'grant update' not in permission and 'grant delete' not in permission
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
    assert "drop constraint manual_publication_approval_events_reason_check" in reason_migration
    assert "reason_min_3_check" in reason_migration
    assert "length(trim(reason)) between 3 and 2000" in reason_migration
    assert "insert into schema_migrations(version) values (57)" in reason_migration
    assert '(57, "manual_publication_reason_length")' in provisioner
    assert "058_publication_worker_mode.sql" in runner
    assert "add column execution_mode text" in (root / "scripts/058_publication_worker_mode.sql").read_text(encoding="utf-8").casefold()
    assert "delete from" not in reason_migration
    assert "update manual_publication_approval_events" not in reason_migration


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


def test_manual_publication_defaults_are_sent_and_match_reason_constraint() -> None:
    root = Path(__file__).resolve().parents[3]
    ui = (root / "apps/dashboard/app/imports/external-import-workspace.tsx").read_text(encoding="utf-8")
    migration = (root / "scripts/057_manual_publication_reason_length.sql").read_text(encoding="utf-8").casefold()
    assert 'useState("admin")' in ui
    assert 'useState("\\uD655\\uC778\\uC644\\uB8CC")' in ui
    assert 'setApprovalActor("admin")' in ui
    assert 'setApprovalReason("\\uD655\\uC778\\uC644\\uB8CC")' in ui
    assert 'reason: approvalReason.trim()' in ui
    assert "const MANUAL_PUBLICATION_REASON_MIN_LENGTH = 3" in ui
    assert "length(trim(reason)) between 3 and 2000" in migration


def test_manual_live_route_keeps_quality_gaps_as_followups_and_has_no_write_call() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "services/api/woori/publications.py").read_text(encoding="utf-8")
    snapshot = source[source.index("def _manual_publication_snapshot"):source.index("def _manual_publication_blockers")]
    blockers = source[source.index("def _manual_publication_blockers"):source.index('@router.get("")')]
    request = source[source.index('@router.post("/manual-live-requests"'):source.index('@router.post("/scheduled-auto/verify-connections")')]
    assert 'followup("source"' in snapshot
    assert 'followup("copyright"' in snapshot
    assert "machine_passed" not in blockers and "publish_ready" not in blockers
    assert 'blockers.append("content_import_link_required")' in snapshot
    assert 'imported["generation_method"] != "manual_codex_import"' not in snapshot
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


def test_database_error_log_records_sqlstate_and_constraint_without_error_payload(caplog: pytest.LogCaptureFixture) -> None:
    class Diagnostic:
        schema_name = "public"
        table_name = "manual_publication_approval_events"
        column_name = ""
        constraint_name = "manual_publication_approval_events_reason_min_3_check"
        message_primary = "prepublication_review_requires_manual_user_confirmation"
        source_function = "require_verified_scheduled_publication_review"

    class DatabaseFailure:
        sqlstate = "23514"
        diag = Diagnostic()

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/admin/publications/manual-live-requests",
        "raw_path": b"/admin/publications/manual-live-requests", "query_string": b"",
        "headers": [], "server": ("127.0.0.1", 8100), "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    with caplog.at_level(logging.ERROR, logger="woori.api.database"):
        response = asyncio.run(database_error(request, DatabaseFailure()))
    assert response.status_code == 503
    response_body = json.loads(response.body)
    assert response_body["error"] == "Database operation unavailable"
    assert response_body["code"] == "database_constraint_violation"
    assert len(response_body["request_id"]) == 24
    assert "sqlstate=23514" in caplog.text
    assert "manual_publication_approval_events_reason_min_3_check" in caplog.text


def test_database_error_does_not_expose_unknown_postgres_message(caplog: pytest.LogCaptureFixture) -> None:
    class Diagnostic:
        schema_name = "public"
        table_name = "publishing_jobs"
        column_name = ""
        constraint_name = ""
        message_primary = "private title must never leak into logs"
        source_function = "some_guard"

    class DatabaseFailure:
        sqlstate = "P0001"
        diag = Diagnostic()

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/admin/publications/manual-live-requests",
        "raw_path": b"/admin/publications/manual-live-requests", "query_string": b"",
        "headers": [], "server": ("127.0.0.1", 8100), "client": ("127.0.0.1", 12345),
    }
    with caplog.at_level(logging.ERROR, logger="woori.api.database"):
        response = asyncio.run(database_error(Request(scope), DatabaseFailure()))
    assert response.status_code == 503
    assert "database_rule_rejected" in caplog.text
    assert "private title" not in caplog.text
    assert "private title" not in response.body.decode()


def test_database_error_classifies_conflict_target_failure_without_sql_text() -> None:
    class Diagnostic:
        schema_name = "unknown"
        table_name = "unknown"
        column_name = "unknown"
        constraint_name = "unknown"
        message_primary = "there is no unique constraint matching the ON CONFLICT specification"
        source_function = "infer_arbiter_indexes"

    class DatabaseFailure:
        sqlstate = "42P10"
        diag = Diagnostic()

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/admin/publications/manual-live-requests",
        "raw_path": b"/admin/publications/manual-live-requests", "query_string": b"",
        "headers": [], "server": ("127.0.0.1", 8100), "client": ("127.0.0.1", 12345),
    }
    response = asyncio.run(database_error(Request(scope), DatabaseFailure()))
    assert response.status_code == 503
    assert json.loads(response.body)["code"] == "db_conflict_target_missing"
    assert "ON CONFLICT" not in response.body.decode()
