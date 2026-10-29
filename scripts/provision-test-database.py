"""Provision the project-only test database and apply its schema without touching ops/eval DBs."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
DB_NAME = "woori_blog_agent_test"
APP_ROLE = "woori_test_app"
OWNER_ROLE = "woori_test_owner"
ENV_PATH = ROOT / ".env.test"
MIGRATIONS = [ROOT / "scripts" / f"{i:03d}_{name}.sql" for i, name in [
    (1, "initial"), (2, "multilingual"), (3, "reference_guards"),
    (4, "config_permissions"), (5, "blogger_oauth"), (6, "content_categories"),
    (7, "research_pipeline"), (8, "research_dispatch"), (9, "pipeline_permissions"),
    (10, "review_order"), (11, "live_research"), (12, "source_revisions"),
    (13, "evaluation_jobs"), (14, "generation_stages"),
    (15, "research_experiment_evaluations"), (16, "evidence_localization"),
    (17, "reviewed_source_language"), (18, "glossary_revision_backfill"),
    (19, "full_article_evaluations"), (20, "article_keywords"),
    (21, "parse_failure_artifacts"), (22, "fact_registry_stage"),
    (23, "worker_heartbeats"), (24, "evaluation_isolation_quotas"),
    (25, "publication_safety"), (26, "publication_scheduling"),
    (27, "article_human_reviews"), (28, "editorial_review_decision"),
    (29, "editorial_versions_and_progress"), (30, "manuscript_editing_metadata"),
    (31, "editorial_existing_post_link"), (32, "editorial_base_hash"),
    (33, "publication_approval"),
    (34, "oauth_write_scope"),
    (35, "trend_observations"),
    (36, "trend_call_quota"),
    (37, "trend_topics_and_packages"),
    (38, "trend_http_status"),
    (39, "trend_grouping_reviews"),
    (40, "research_package_review_state"),
    (41, "editorial_seo_metadata"),
    (42, "publication_modes"),
    (43, "localized_publication_requests"),
    (44, "localized_request_recovery"),
    (45, "external_content_imports"),
    (46, "trend_topic_categories"), (47, "import_review_pipeline"),
    (48, "import_content_version_bridge"),
    (49, "blogger_live_publication_queue"),
    (50, "trends_eleven_geographies"),
    (51, "trend_approx_traffic"),
]]


def target_url(base: str, database: str, role: str, password: str) -> str:
    parsed = urlsplit(base)
    return f"postgresql://{role}:{quote(password, safe='')}@{parsed.hostname}:{parsed.port}/{database}"


bootstrap = dotenv_values(ROOT / ".env.bootstrap").get("BOOTSTRAP_DATABASE_URL")
if not bootstrap:
    raise SystemExit("Local bootstrap connection is not configured; no database changes made.")
admin_info = urlsplit(bootstrap)
if (admin_info.hostname not in {"127.0.0.1", "localhost", "::1"}
        or admin_info.port != 5432 or admin_info.path.lstrip("/") != "postgres"
        or admin_info.username != "postgres"):
    raise SystemExit("Bootstrap target identity is not the expected local PostgreSQL admin endpoint.")

existing_env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
if ENV_PATH.exists():
    app_url = existing_env.get("DATABASE_URL", "")
    owner_url = existing_env.get("MIGRATION_DATABASE_URL", "")
    app_info, owner_info = urlsplit(app_url), urlsplit(owner_url)
    if (app_info.username != APP_ROLE or app_info.path.lstrip("/") != DB_NAME
            or owner_info.username != OWNER_ROLE or owner_info.path.lstrip("/") != DB_NAME
            or app_info.hostname not in {"localhost", "127.0.0.1", "::1"}
            or owner_info.hostname not in {"localhost", "127.0.0.1", "::1"}
            or app_info.port != 5432 or owner_info.port != 5432):
        raise SystemExit("Existing .env.test identities do not match; refusing rotation or overwrite.")
else:
    app_url = owner_url = ""

with psycopg.connect(bootstrap, autocommit=True, connect_timeout=5) as admin:
    roles = {row[0] for row in admin.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN (%s,%s)", (APP_ROLE, OWNER_ROLE)
    )}
    db_row = admin.execute(
        "SELECT pg_get_userbyid(datdba),datacl FROM pg_database WHERE datname=%s", (DB_NAME,)
    ).fetchone()
    if ENV_PATH.exists() and not {APP_ROLE, OWNER_ROLE}.issubset(roles):
        raise SystemExit(".env.test exists but its dedicated roles are missing; refusing repair or rotation.")
    if not ENV_PATH.exists() and (roles or db_row):
        raise SystemExit("Test database objects already exist without .env.test; refusing credential replacement.")

    if not ENV_PATH.exists():
        app_password = secrets.token_urlsafe(36)
        owner_password = secrets.token_urlsafe(36)
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}")
                      .format(sql.Identifier(OWNER_ROLE), sql.Literal(owner_password)))
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}")
                      .format(sql.Identifier(APP_ROLE), sql.Literal(app_password)))
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'")
                      .format(sql.Identifier(DB_NAME), sql.Identifier(OWNER_ROLE)))
        app_url = target_url(bootstrap, DB_NAME, APP_ROLE, app_password)
        owner_url = target_url(bootstrap, DB_NAME, OWNER_ROLE, owner_password)
        ENV_PATH.write_text(f"DATABASE_URL={app_url}\nMIGRATION_DATABASE_URL={owner_url}\n", encoding="utf-8")

    if db_row and db_row[0] != OWNER_ROLE:
        raise SystemExit("Existing test database has an unexpected owner; refusing changes.")
    admin.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DB_NAME)))
    admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
        sql.Identifier(DB_NAME), sql.Identifier(APP_ROLE), sql.Identifier(OWNER_ROLE)))

with psycopg.connect(owner_url, connect_timeout=5) as conn:
    current_row = conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()
    current = 0 if not current_row or current_row[0] is None else conn.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone()[0]
    if current > len(MIGRATIONS):
        raise SystemExit("Test DB schema is newer than this checkout; refusing downgrade.")
    for number, path in enumerate(MIGRATIONS, start=1):
        if number > current:
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"), prepare=False)
    with conn.transaction():
        conn.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}")
                     .format(sql.Identifier(APP_ROLE)))
        conn.execute(sql.SQL("GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}")
                     .format(sql.Identifier(APP_ROLE)))
        conn.execute(sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {}")
                     .format(sql.Identifier(APP_ROLE)))
    version = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    identity = conn.execute(
        "SELECT current_database(),current_user,inet_server_addr()::text"
    ).fetchone()
    assert version == len(MIGRATIONS) and identity[0] == DB_NAME and identity[1] == OWNER_ROLE

app_identity_ok = False
with psycopg.connect(app_url, connect_timeout=5) as app_conn:
    app_identity_ok = app_conn.execute(
        "SELECT current_database()=%s AND current_user=%s AND has_table_privilege(current_user,'content_versions','INSERT')",
        (DB_NAME, APP_ROLE),
    ).fetchone()[0]
if not app_identity_ok:
    raise SystemExit("Test application identity or scoped privileges did not validate.")

ops_url = dotenv_values(ROOT / ".env.migration").get("MIGRATION_DATABASE_URL", "")
ops_host = urlsplit(ops_url).hostname
if not ops_url or ops_host not in {"127.0.0.1", "localhost", "::1"}:
    raise SystemExit("Could not verify the local operations DB identity; refusing test DB validation.")
ops_denied = False
ops_parts = urlsplit(ops_url)
try:
    denied_url = target_url(app_url, ops_parts.path.lstrip("/"), APP_ROLE,
                            urlsplit(app_url).password or "")
    with psycopg.connect(denied_url, connect_timeout=4):
        pass
except psycopg.OperationalError as exc:
    # Windows may localize the connection error and leave SQLSTATE unset. Confirm
    # the local server is reachable and the role has no effective CONNECT grant.
    with psycopg.connect(bootstrap, connect_timeout=4) as admin:
        granted = admin.execute(
            "SELECT has_database_privilege(%s,%s,'CONNECT')", (APP_ROLE, ops_parts.path.lstrip("/"))
        ).fetchone()[0]
    ops_denied = exc.sqlstate == "42501" or not granted
if not ops_denied:
    raise SystemExit("Test login can connect to the operations DB; access isolation did not validate.")

print(f"Test DB ready: {DB_NAME}, schema {len(MIGRATIONS)}; isolated app and owner roles verified.")
print("Operations DB connection denial for the test app role: verified.")
