import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from woori.config import settings
from woori.db import connection
from woori.main import app
from woori.worker import tick


def test_database_audit_and_worker() -> None:
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
        with pytest.raises(psycopg.Error), connection() as conn:
            conn.execute(statement)
    with connection() as conn:
        assert not conn.execute(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()["?column?"]


def test_content_versions_and_lease_recovery() -> None:
    with connection() as conn:
        group = conn.execute("INSERT INTO content_groups DEFAULT VALUES RETURNING id").fetchone()[
            "id"
        ]
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
    with connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM content_versions WHERE group_id=%s", (group,)
            ).fetchone()["n"]
            == 3
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM audit_events WHERE event_type='run.failed'"
            ).fetchone()["n"]
            >= 1
        )
    for statement in [
        "DELETE FROM content_versions WHERE id=%s",
        "UPDATE content_versions SET title=title WHERE id=%s",
    ]:
        with pytest.raises(psycopg.Error), connection() as conn:
            conn.execute(statement, (source,))
