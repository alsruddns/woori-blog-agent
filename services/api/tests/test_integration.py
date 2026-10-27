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
