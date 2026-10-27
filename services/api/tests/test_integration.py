import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from woori.config import settings
from woori.db import connection
from woori.main import app
from woori.worker import tick


@pytest.fixture
def rollback_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[psycopg.Connection[dict[str, object]]]:
    """Keep integration-test writes inside one outer transaction and assert rollback."""
    base_connection = connection
    with base_connection() as conn, conn.transaction(force_rollback=True):
        initial_versions = conn.execute(
            "SELECT count(*) AS n FROM content_versions"
        ).fetchone()["n"]
        initial_audits = conn.execute(
            "SELECT count(*) AS n FROM audit_events"
        ).fetchone()["n"]

        @contextmanager
        def shared() -> Iterator[psycopg.Connection[dict[str, object]]]:
            with conn.transaction():
                yield conn

        # API and Worker must use the same rollback-only connection. The test
        # module's direct database access is patched too, so no helper opens a
        # separately committed connection by accident.
        monkeypatch.setattr("woori.main.connection", shared)
        monkeypatch.setattr("woori.worker.connection", shared)
        monkeypatch.setattr(__name__ + ".connection", shared)
        yield conn

    # Verify persisted state after the outer rollback using a fresh connection.
    with base_connection() as verify_conn:
        assert (
            verify_conn.execute("SELECT count(*) AS n FROM content_versions").fetchone()["n"]
            == initial_versions
        )
        assert (
            verify_conn.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"]
            == initial_audits
        )


def test_pytest_application_connections_force_rollback() -> None:
    # Tests only connect to the dedicated test DB; its login is denied CONNECT
    # to operations and application writes remain inside forced rollback.
    with connection() as conn:
        identity = conn.execute(
            """SELECT current_database() AS db,current_user AS role,
               has_database_privilege(current_user,'woori_blog_agent','CONNECT') AS ops_connect"""
        ).fetchone()
        assert identity == {"db": "woori_blog_agent_test", "role": "woori_test_app", "ops_connect": False}
        before = conn.execute("SELECT count(*) AS n FROM content_groups").fetchone()["n"]
    with connection() as conn:
        conn.execute("INSERT INTO content_groups DEFAULT VALUES")
    with connection() as conn:
        after = conn.execute("SELECT count(*) AS n FROM content_groups").fetchone()["n"]
    assert before == after


def test_database_audit_and_worker(
    rollback_lab: psycopg.Connection[dict[str, object]],
) -> None:
    key = "integration-" + uuid.uuid4().hex
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + settings().admin_token}
        first = client.post("/admin/runs", headers=headers, json={"idempotency_key": key})
        assert first.status_code == 201
        second = client.post("/admin/runs", headers=headers, json={"idempotency_key": key})
        assert first.json()["id"] == second.json()["id"]
        tick()
        result = client.get("/admin/summary", headers=headers)
        assert result.status_code == 200
        assert any(x["event_type"] == "run.completed" for x in result.json()["events"])
    for statement in [
        "UPDATE audit_events SET event_type=event_type",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
        "UPDATE content_versions SET title=title",
        "CREATE TABLE forbidden(id int)",
    ]:
        with pytest.raises(psycopg.Error), rollback_lab.transaction():
            rollback_lab.execute(statement)
    assert not rollback_lab.execute(
        "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
    ).fetchone()["?column?"]


def test_content_versions_and_lease_recovery(
    rollback_lab: psycopg.Connection[dict[str, object]],
) -> None:
    conn = rollback_lab
    group = conn.execute("INSERT INTO content_groups DEFAULT VALUES RETURNING id").fetchone()["id"]
    source = conn.execute(
        "INSERT INTO content_versions(group_id,language,version,title,body) VALUES (%s,'ko',1,'original','body') RETURNING id",
        (group,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO content_versions(group_id,language,version,title,body,source_version_id) VALUES (%s,'en',1,'localized','body',%s)",
        (group, source),
    )
    conn.execute(
        "INSERT INTO content_versions(group_id,language,version,title,body) VALUES (%s,'ko',2,'revised','new body')",
        (group,),
    )
    conn.execute(
        "INSERT INTO job_runs(idempotency_key,status,attempts,lease_until) VALUES (%s,'running',3,now()-interval '1 minute')",
        ("expired-" + uuid.uuid4().hex,),
    )
    tick()
    assert conn.execute(
        "SELECT count(*) AS n FROM content_versions WHERE group_id=%s", (group,)
    ).fetchone()["n"] == 3
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_events WHERE event_type='run.failed'"
    ).fetchone()["n"] >= 1
    for statement in [
        "DELETE FROM content_versions WHERE id=%s",
        "UPDATE content_versions SET title=title WHERE id=%s",
    ]:
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute(statement, (source,))


def test_publication_approval_and_revocation_on_isolated_database(
    rollback_lab: psycopg.Connection[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from hashlib import sha256

    from fastapi import HTTPException
    from woori import research_routes

    evaluation_id, version_id = uuid.uuid4(), uuid.uuid4()
    body = "Verified isolated test manuscript"
    body_hash = sha256(body.encode("utf-8")).hexdigest()
    rollback_lab.execute(
        """INSERT INTO article_human_reviews(evaluation_id,content_version_id,idempotency_key,
           reviewer_name,factual_accuracy,translation_naturalness,reader_value,disposition,comments)
           VALUES (%s,%s,%s,'Test Reviewer','verified','acceptable','useful','approved',
           'Explicit isolated database approval fixture')""",
        (evaluation_id, version_id, "test-review-" + uuid.uuid4().hex[:20]),
    )

    @contextmanager
    def shared() -> Iterator[psycopg.Connection[dict[str, object]]]:
        with rollback_lab.transaction():
            yield rollback_lab

    monkeypatch.setattr(research_routes, "connection", shared)
    monkeypatch.setattr(
        research_routes,
        "_evaluation_article",
        lambda *_: {"machine_passed": True, "saved_body": body},
    )
    approve = research_routes.PublicationApproval(
        evaluation_id=evaluation_id,
        content_version_id=version_id,
        event_key="test-approval-" + uuid.uuid4().hex[:20],
        actor="Test Reviewer",
        action="approved",
        reason="Approved only to exercise isolated workflow persistence.",
    )
    accepted = research_routes.record_publication_approval(approve)
    assert accepted["publish_ready"] is False
    assert accepted["live_blogger_write"] is False
    approval_id = accepted["event"]["id"]
    assert accepted["event"]["body_sha256"].strip() == body_hash

    revoked = research_routes.record_publication_approval(
        research_routes.PublicationApproval(
            evaluation_id=evaluation_id,
            content_version_id=version_id,
            event_key="test-revocation-" + uuid.uuid4().hex[:20],
            actor="Test Reviewer",
            action="revoked",
            reason="Revoke the isolated test approval immediately.",
            supersedes_event_id=approval_id,
        )
    )
    assert revoked["event"]["action"] == "revoked"
    assert revoked["publish_ready"] is False
    assert rollback_lab.execute(
        "SELECT count(*) AS n FROM publication_approval_events WHERE evaluation_id=%s",
        (evaluation_id,),
    ).fetchone()["n"] == 2
    assert rollback_lab.execute(
        "SELECT count(*) AS n FROM audit_events WHERE event_type='article.publication_approval.recorded'"
    ).fetchone()["n"] >= 2

    edited_id = uuid.uuid4()
    rollback_lab.execute(
        """INSERT INTO article_editorial_versions(id,evaluation_id,base_content_version_id,
           revision_number,idempotency_key,reviewer_name,reason,title,body,summary,keywords,
           machine_checks,machine_passed,quality_status,body_sha256)
           VALUES (%s,%s,%s,1,%s,'Test Editor','Version-change invalidation fixture',
           'Edited title','Edited body','Edited summary',ARRAY['updated'], '{}'::jsonb,true,
           'machine_checked_review_required',%s)""",
        (edited_id,evaluation_id,version_id,"test-edit-"+uuid.uuid4().hex[:20],sha256(b"Edited body").hexdigest()),
    )
    with pytest.raises(HTTPException) as conflict:
        research_routes.record_publication_approval(approve.model_copy(update={
            "event_key": "test-after-edit-" + uuid.uuid4().hex[:20],
        }))
    assert conflict.value.status_code == 409
    assert rollback_lab.execute(
        """SELECT count(*) AS n FROM audit_events
           WHERE event_type='article.publication_approval.recorded'
             AND payload->>'publish_ready'='true'"""
    ).fetchone()["n"] == 0


def test_editorial_save_sanitizes_versions_and_rejects_stale_editor(
    rollback_lab: psycopg.Connection[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from woori import article_quality, research_routes

    source_id = uuid4()
    evaluation_id, content_version_id = uuid4(), uuid4()
    source = {
        "source_ids": [str(source_id)],
        "language_code": "en",
        "facts": [{}],
        "saved_body": "Original verified test body with a source citation.",
        "sources": [{
            "id": str(source_id), "source_name": "Synthetic test source",
            "url": "https://example.gov/test-source",
            "evidence": "This synthetic fixture is only for isolated editor integration tests.",
            "rights": "Authored test fixture; no third-party content.",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }],
    }

    @contextmanager
    def shared() -> Iterator[psycopg.Connection[dict[str, object]]]:
        with rollback_lab.transaction():
            yield rollback_lab

    monkeypatch.setattr(research_routes, "connection", shared)
    monkeypatch.setattr(research_routes, "_evaluation_article", lambda *_: source)
    monkeypatch.setattr(article_quality, "evaluate", lambda *_: {"checks": {}, "machine_passed": True})
    with TestClient(app) as client:
        auth = {"Authorization": "Bearer " + settings().admin_token}
        first_response = client.post(
            "/admin/research/article-revisions",
            headers=auth,
            json={
                "evaluation_id": str(evaluation_id), "content_version_id": str(content_version_id),
                "idempotency_key": "test-editor-first-" + uuid.uuid4().hex[:18],
                "reviewer_name": "Test Editor", "reason": "Exercise isolated first revision save.",
                "title": "Verified test article", "body": "A safe text alternative with enough content.",
                "html_body": '<h2 onclick="bad()">Facts</h2><p>Verified test text with <strong>formatting</strong>.</p><script>bad()</script>',
                "summary": "A synthetic editorial description.", "seo_description": "A synthetic SEO description.",
                "keywords": ["synthetic test"], "blogger_labels": ["test"],
                "publication_mode": "manual",
            },
        )
        assert first_response.status_code == 201, first_response.text
        first = first_response.json()["revision"]
        assert first["revision_number"] == 1
        assert first_response.json()["publish_ready"] is False
        assert "<script" not in first["html_body"] and "onclick" not in first["html_body"]

        stale = client.post(
            "/admin/research/article-revisions",
            headers=auth,
            json={
                "evaluation_id": str(evaluation_id), "content_version_id": str(content_version_id),
                "idempotency_key": "test-editor-stale-" + uuid.uuid4().hex[:18],
                "reviewer_name": "Test Editor", "reason": "Exercise stale editor conflict handling.",
                "title": "Stale title", "body": "A stale update with sufficient body content.",
                "summary": "A stale synthetic description.", "keywords": ["synthetic test"],
            },
        )
        assert stale.status_code == 409

        second_response = client.post(
            "/admin/research/article-revisions",
            headers=auth,
            json={
                "evaluation_id": str(evaluation_id), "content_version_id": str(content_version_id),
                "base_editorial_version_id": first["id"],
                "idempotency_key": "test-editor-next-" + uuid.uuid4().hex[:18],
                "reviewer_name": "Test Editor", "reason": "Save the next isolated immutable version.",
                "title": "Verified test article v2", "body": "The second verified test body is sufficiently long.",
                "summary": "A revised synthetic description.", "keywords": ["synthetic test"],
            },
        )
        assert second_response.status_code == 201, second_response.text
        second = second_response.json()["revision"]
        assert second["revision_number"] == 2
        assert second["id"] != first["id"]
        assert second_response.json()["publish_ready"] is False

    rows = rollback_lab.execute(
        "SELECT revision_number FROM article_editorial_versions WHERE evaluation_id=%s ORDER BY revision_number",
        (evaluation_id,),
    ).fetchall()
    assert [row["revision_number"] for row in rows] == [1, 2]
    assert rollback_lab.execute(
        "SELECT count(*) AS n FROM audit_events WHERE event_type='article.editorial_revision.saved'"
    ).fetchone()["n"] >= 2
