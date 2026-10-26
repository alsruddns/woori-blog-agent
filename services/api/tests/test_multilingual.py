import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from psycopg import sql
from woori.config import settings
from woori.db import connection
from woori.main import app
from woori.multilingual import language_tag, readiness


@pytest.mark.parametrize("code", ["ko", "en", "zh-CN", "zh-TW", "ja", "es", "fr", "de", "pt-BR"])
def test_bcp47(code: str) -> None:
    assert language_tag(code) == code


@pytest.mark.parametrize(
    ("raw", "canonical"), [("zh-cn", "zh-CN"), ("pt-br", "pt-BR"), ("EN", "en")]
)
def test_tag_normalization(raw: str, canonical: str) -> None:
    assert language_tag(raw) == canonical


@pytest.mark.parametrize("code", ["", "en_US", "zzzz", "en--US", "../../ko"])
def test_invalid_tag(code: str) -> None:
    with pytest.raises(ValueError):
        language_tag(code)


def test_untrusted_capability_flags_do_not_enable_adapters() -> None:
    row = {
        "language_code": "es",
        "generation_supported": True,
        "translation_supported": True,
        "quality_supported": True,
        "model_adapter": "untrusted",
        "validator_adapter": "untrusted",
        "blog_id": "123",
        "connection_verified_at": "now",
        "test_publish_verified_at": "now",
    }
    result = readiness(row)
    assert not result["generation_possible"]
    assert not result["translation_possible"]
    assert not result["quality_possible"]
    assert not result["automatic_publishing_allowed"]


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    # API calls commit savepoints; outer rollback prevents synthetic configuration pollution.
    with connection() as conn, conn.transaction(force_rollback=True):

        @contextmanager
        def shared() -> Iterator[psycopg.Connection[dict[str, Any]]]:
            with conn.transaction():
                yield conn

        monkeypatch.setattr("woori.multilingual.connection", shared)
        monkeypatch.setattr("woori.main.connection", shared)
        yield conn


def test_configuration_lifecycle(sandbox: psycopg.Connection[dict[str, Any]]) -> None:
    headers = {"Authorization": "Bearer " + settings().admin_token}
    code = "es-x-" + uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        assert client.get("/admin/config").status_code == 401
        registered = client.post(
            "/admin/config/languages",
            headers=headers,
            json={"code": code, "display_name": "Espa梨컊l"},
        )
        assert registered.status_code == 201, registered.text
        assert (
            client.post(
                "/admin/config/languages",
                headers=headers,
                json={"code": code, "display_name": "duplicate"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/admin/config/languages",
                headers=headers,
                json={"code": "en_US", "display_name": "invalid"},
            ).status_code
            == 422
        )
        blogs = []
        for _ in range(2):
            blog = client.post(
                "/admin/config/blogs",
                headers=headers,
                json={
                    "language_code": code,
                    "url": "https://integration-" + uuid.uuid4().hex + ".blogspot.com/",
                    "display_name": "Test only",
                },
            )
            assert blog.status_code == 201, blog.text
            assert blog.json()["blog_id"] is None
            blogs.append(blog.json())
        assert (
            client.post(
                "/admin/config/blogs",
                headers=headers,
                json={
                    "language_code": code,
                    "url": "https://evil.example",
                    "display_name": "invalid",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/admin/config/blogs",
                headers=headers,
                json={
                    "language_code": code,
                    "url": "https://id-forbidden.blogspot.com",
                    "display_name": "invalid",
                    "blog_id": "123",
                },
            ).status_code
            == 422
        )
        profiles = []
        for country in ["ES", "MX"]:
            p = client.post(
                "/admin/config/profiles",
                headers=headers,
                json={
                    "language_code": code,
                    "target_country": country,
                    "search_intent": "regional search",
                    "seo_policy": "Validate independent keywords and sources",
                },
            )
            assert p.status_code == 200, p.text
            profiles.append(p.json())
        policy = client.post(
            "/admin/config/policies",
            headers=headers,
            json={
                "blog_id": blogs[0]["id"],
                "profile_id": profiles[0]["id"],
                "timezone": "Europe/Madrid",
                "schedule_cron": "0 9 * * *",
                "active": True,
            },
        )
        assert policy.status_code == 200, policy.text
        assert not policy.json()["auto_publish_allowed"]
        assert (
            client.post(
                "/admin/config/policies",
                headers=headers,
                json={
                    "blog_id": blogs[0]["id"],
                    "profile_id": profiles[0]["id"],
                    "auto_publish_allowed": True,
                },
            ).status_code
            == 422
        )
        for field, value in [("timezone", "Not/AZone"), ("schedule_cron", "99 99 * * *")]:
            assert (
                client.post(
                    "/admin/config/policies",
                    headers=headers,
                    json={"blog_id": blogs[0]["id"], "profile_id": profiles[0]["id"], field: value},
                ).status_code
                == 422
            )
        other = sandbox.execute(
            "SELECT id FROM language_profiles WHERE language_code='ko' LIMIT 1"
        ).fetchone()
        assert (
            client.post(
                "/admin/config/policies",
                headers=headers,
                json={"blog_id": blogs[0]["id"], "profile_id": str(other["id"])},
            ).status_code
            == 409
        )
        category_response = client.post(
            "/admin/config/categories", headers=headers, json={"slug": "test-" + uuid.uuid4().hex}
        )
        assert category_response.status_code == 201, category_response.text
        category = category_response.json()
        assert (
            client.post(
                "/admin/config/category-localizations",
                headers=headers,
                json={
                    "category_id": category["id"],
                    "profile_id": profiles[0]["id"],
                    "display_name": "Noticias",
                },
            ).status_code
            == 200
        )
        glossary_response = client.post(
                "/admin/config/glossary",
                headers=headers,
                json={
                    "profile_id": profiles[0]["id"],
                    "source_term": "stock",
                    "localized_term": "acci泥쁭",
                },
            )
        assert glossary_response.status_code == 200
        assert glossary_response.json()["approved"] is False
        entry_id = glossary_response.json()["id"]
        assert sandbox.execute(
            "SELECT count(*) AS n FROM glossary_entry_revisions WHERE entry_id=%s", (entry_id,)
        ).fetchone()["n"] == 1
        assert client.post(
            "/admin/config/glossary", headers=headers,
            json={"profile_id": profiles[0]["id"], "source_term": "stock",
                  "localized_term": "acción", "approved": True,
                  "official_translation": True, "source_language": "en"},
        ).status_code == 422
        approved_glossary = client.post(
            "/admin/config/glossary", headers=headers,
            json={"profile_id": profiles[0]["id"], "source_term": "stock",
                  "localized_term": "acción", "approved": True,
                  "official_translation": True,
                  "source_language": "en",
                  "translation_source": "https://example.org/controlled-test-glossary"},
        )
        assert approved_glossary.status_code == 200, approved_glossary.text
        assert sandbox.execute(
            "SELECT count(*) AS n FROM glossary_entry_revisions WHERE entry_id=%s", (entry_id,)
        ).fetchone()["n"] == 2
        assert (
            client.patch(
                "/admin/config/languages/" + code,
                headers=headers,
                json={"display_name": "Spanish disabled", "active": False},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                "/admin/config/blogs/" + blogs[0]["id"],
                headers=headers,
                json={"display_name": "Disabled test blog", "active": False},
            ).status_code
            == 200
        )
        config = client.get("/admin/config", headers=headers).json()
        assert len([b for b in config["blogs"] if b["language_code"] == code]) == 2
        states = [r for r in config["readiness"] if r["language_code"] == code]
        assert states and all(not r["automatic_publishing_allowed"] for r in states)
        assert any(
            l["code"] == code
            for l in client.get("/admin/summary", headers=headers).json()["language_details"]
        )
        assert client.delete("/admin/config/languages/" + code, headers=headers).status_code == 405
    assert (
        sandbox.execute(
            "SELECT count(*) AS n FROM audit_events WHERE language_code=%s", (code,)
        ).fetchone()["n"]
        >= 10
    )
    with pytest.raises(psycopg.Error), sandbox.transaction():
        sandbox.execute("DELETE FROM languages WHERE code=%s", (code,))
    with pytest.raises(psycopg.Error), sandbox.transaction():
        sandbox.execute(
            "UPDATE publishing_policies SET auto_publish_allowed=true WHERE id=%s",
            (policy.json()["id"],),
        )


def test_legacy_migration_preserves_content_and_audits() -> None:
    root = Path(__file__).resolve().parents[3]
    url = dotenv_values(root / ".env.migration")["MIGRATION_DATABASE_URL"]
    schema = "test_migration_" + uuid.uuid4().hex
    with psycopg.connect(url) as conn, conn.transaction(force_rollback=True):
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
        initial = (
            (root / "scripts/001_initial.sql")
            .read_text(encoding="utf-8")
            .replace("SCHEMA public", "SCHEMA " + schema)
        )
        conn.execute(initial, prepare=False)
        group = conn.execute("INSERT INTO content_groups DEFAULT VALUES RETURNING id").fetchone()[0]
        original = conn.execute(
            "INSERT INTO content_versions(group_id,language,version,title,body) VALUES (%s,'ko',1,'preserve title','preserve body') RETURNING *",
            (group,),
        ).fetchone()
        event = conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('test.preserved',jsonb_build_object('unchanged',true)) RETURNING *"
        ).fetchone()
        for migration in [
            "002_multilingual.sql",
            "003_reference_guards.sql",
            "004_config_permissions.sql",
            "005_blogger_oauth.sql",
            "006_content_categories.sql",
            "007_research_pipeline.sql",
            "008_research_dispatch.sql",
            "009_pipeline_permissions.sql",
            "010_review_order.sql",
            "011_live_research.sql",
            "012_source_revisions.sql",
            "013_evaluation_jobs.sql",
            "014_generation_stages.sql",
            "015_research_experiment_evaluations.sql",
            "016_evidence_localization.sql",
            "017_reviewed_source_language.sql",
            "018_glossary_revision_backfill.sql",
            "019_full_article_evaluations.sql",
            "020_article_keywords.sql",
            "021_parse_failure_artifacts.sql",
            "022_fact_registry_stage.sql",
            "023_worker_heartbeats.sql",
            "024_evaluation_isolation_quotas.sql",
        ]:
            content = (
                (root / "scripts" / migration)
                .read_text(encoding="utf-8")
                .replace("SCHEMA public", "SCHEMA " + schema)
            )
            conn.execute(content, prepare=False)
        after = conn.execute(
            "SELECT id,group_id,language,version,title,body,source_version_id,created_at FROM content_versions WHERE id=%s",
            (original[0],),
        ).fetchone()
        assert after == original
        assert (
            conn.execute(
                "SELECT id,run_id,event_type,payload,created_at FROM audit_events WHERE id=%s",
                (event[0],),
            ).fetchone()
            == event
        )
        assert (
            conn.execute("SELECT count(*) FROM blogger_blogs WHERE blog_id IS NULL").fetchone()[0]
            == 4
        )
        for statement in [
            "UPDATE audit_events SET event_type=event_type",
            "UPDATE content_versions SET title=title",
            "TRUNCATE publishing_records",
        ]:
            with pytest.raises(psycopg.Error), conn.transaction():
                conn.execute(statement)
        conn.execute("INSERT INTO languages(code,display_name) VALUES ('es','Spanish')")
        first = conn.execute(
            "INSERT INTO content_versions(group_id,language,version,title,body) VALUES (%s,'es',1,'Spanish','first') RETURNING id,localization_id",
            (group,),
        ).fetchone()
        conn.execute(
            "INSERT INTO content_versions(group_id,language,version,title,body,source_version_id) VALUES (%s,'es',2,'Spanish revision','second',%s)",
            (group, first[0]),
        )
        conn.execute("UPDATE languages SET active=false WHERE code='es'")
        assert (
            conn.execute(
                "SELECT count(*) FROM content_versions WHERE localization_id=%s", (first[1],)
            ).fetchone()[0]
            == 2
        )
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute("UPDATE languages SET code='fr' WHERE code='es'")


def test_regional_versions_and_publishing_reference_retention() -> None:
    root = Path(__file__).resolve().parents[3]
    url = dotenv_values(root / ".env.migration")["MIGRATION_DATABASE_URL"]
    # Owner used only to insert synthetic publishing history into a rolled-back test transaction.
    with psycopg.connect(url) as conn, conn.transaction(force_rollback=True):
        code = "pt-x-" + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO languages(code,display_name) VALUES (%s,%s)", (code, "Test Portuguese")
        )
        group = conn.execute("INSERT INTO content_groups DEFAULT VALUES RETURNING id").fetchone()[0]
        profiles = []
        versions = []
        for country in ["BR", "PT"]:
            profile = conn.execute(
                "INSERT INTO language_profiles(language_code,target_country) VALUES (%s,%s) RETURNING id",
                (code, country),
            ).fetchone()[0]
            profiles.append(profile)
            localization = conn.execute(
                "INSERT INTO content_localizations(group_id,language_code,target_country) VALUES (%s,%s,%s) RETURNING id",
                (group, code, country),
            ).fetchone()[0]
            version = conn.execute(
                "INSERT INTO content_versions(group_id,language,localization_id,version,title,body) VALUES (%s,%s,%s,1,'region title','region body') RETURNING id",
                (group, code, localization),
            ).fetchone()[0]
            versions.append(version)
        blog = conn.execute(
            "INSERT INTO blogger_blogs(language_code,url,display_name) VALUES (%s,%s,'Synthetic test') RETURNING id",
            (code, "https://integration-" + uuid.uuid4().hex + ".blogspot.com"),
        ).fetchone()[0]
        policy = conn.execute(
            "INSERT INTO publishing_policies(language_code,blog_id,profile_id) VALUES (%s,%s,%s) RETURNING id",
            (code, blog, profiles[0]),
        ).fetchone()[0]
        job = conn.execute(
            "INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at) VALUES (%s,%s,%s,%s,now()) RETURNING id",
            (policy, blog, versions[0], uuid.uuid4().hex),
        ).fetchone()[0]
        record = conn.execute(
            "INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,published_at) VALUES (%s,%s,%s,'synthetic-no-network',now()) RETURNING id",
            (job, blog, versions[0]),
        ).fetchone()[0]
        for statement, params in [
            (
                "INSERT INTO publishing_jobs(policy_id,blog_id,content_version_id,idempotency_key,scheduled_at) VALUES (%s,%s,%s,%s,now())",
                (policy, blog, versions[1], uuid.uuid4().hex),
            ),
            (
                "INSERT INTO seo_audits(content_version_id,profile_id,validator_adapter,checks) VALUES (%s,%s,'test','{}')",
                (versions[1], profiles[0]),
            ),
            ("UPDATE publishing_records SET remote_post_id=remote_post_id WHERE id=%s", (record,)),
            ("DELETE FROM publishing_records WHERE id=%s", (record,)),
        ]:
            with pytest.raises(psycopg.Error), conn.transaction():
                conn.execute(statement, params)
        conn.execute("UPDATE languages SET active=false WHERE code=%s", (code,))
        conn.execute("UPDATE blogger_blogs SET active=false WHERE id=%s", (blog,))
        assert (
            conn.execute("SELECT id FROM publishing_records WHERE id=%s", (record,)).fetchone()[0]
            == record
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM content_versions WHERE group_id=%s", (group,)
            ).fetchone()[0]
            == 2
        )
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute("DELETE FROM languages WHERE code=%s", (code,))
