"""Create a least-privilege evaluation DB from a secret-free project snapshot."""

from __future__ import annotations

import os
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from dotenv import dotenv_values
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
DB = "woori_blog_agent_eval"
OWNER = "woori_eval_owner"
APP = "woori_eval_app"
READER = "woori_eval_reader"
IDENTITY = "woori_eval_identity"
BIN = Path("C:/Program Files/PostgreSQL/16/bin")
EXCLUDED_DATA = (
    "audit_events", "google_connections", "google_oauth_states", "blogger_blogs",
    "blogger_api_calls", "blogger_write_operations", "publishing_policies",
    "publishing_jobs", "publishing_records", "publication_state_events", "publication_attempts",
    "publication_schedule_events", "search_performance", "worker_heartbeats",
)


def fail(message: str) -> None:
    raise SystemExit(message)


def pg_args(url: str, inherited: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.path.count("/") != 1:
        fail("A project PostgreSQL URL is required")
    args = ["--host", parsed.hostname or "127.0.0.1", "--port", str(parsed.port or 5432),
            "--username", unquote(parsed.username or "")]
    env = dict(inherited or os.environ)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return args, env


admin_url = dotenv_values(ROOT / ".env.bootstrap").get("BOOTSTRAP_DATABASE_URL", "")
ops_url = dotenv_values(ROOT / ".env.migration").get("MIGRATION_DATABASE_URL", "")
if not admin_url or not ops_url:
    fail("Bootstrap and project migration configuration are required")
admin_target = urlsplit(admin_url)
if (admin_target.hostname or "localhost").lower() not in {"localhost", "127.0.0.1", "::1"}:
    fail("Only the configured local PostgreSQL administrator is permitted")
if urlsplit(ops_url).path != "/woori_blog_agent":
    fail("Refusing a source database other than woori_blog_agent")

role_files = {
    "migration": ROOT / ".env.evaluation-migration",
    "application": ROOT / ".env.evaluation",
    "reader": ROOT / ".env.evaluation-readonly",
}
with psycopg.connect(admin_url, autocommit=True, row_factory=psycopg.rows.dict_row) as admin:
    target = admin.execute("SELECT current_user AS role,inet_server_addr()::text AS address").fetchone()
    if not target or target["role"] != "postgres" or (target["address"] or "").split("/")[0] not in {"127.0.0.1", "::1"}:
        fail("The local PostgreSQL administrator identity could not be confirmed")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname='woori_blog_agent'").fetchone():
        fail("The existing project database was not found")
    found = admin.execute("SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)", ([OWNER, APP, READER, IDENTITY],)).fetchall()
    db_exists = bool(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB,)).fetchone())
    if found or db_exists:
        if len(found) != 4 or not db_exists or not all(path.exists() for path in role_files.values()):
            fail("Partial evaluation resources exist; refusing to change or replace them")
        owner_row = admin.execute(
            "SELECT pg_get_userbyid(datdba) owner FROM pg_database WHERE datname=%s", (DB,)
        ).fetchone()
        if not owner_row or owner_row["owner"] != OWNER:
            fail("The existing evaluation database has an unexpected owner")
        migration_url = dotenv_values(role_files["migration"]).get("MIGRATION_DATABASE_URL", "")
        app_url = dotenv_values(role_files["application"]).get("DATABASE_URL", "")
        identity_url = dotenv_values(role_files["application"]).get("WOORI_OPERATION_DATABASE_URL", "")
        reader_url = dotenv_values(role_files["reader"]).get("EVALUATION_DATABASE_URL", "")
        if any(urlsplit(url).path != f"/{DB}" for url in (migration_url, app_url, reader_url)):
            fail("Existing evaluation connection files point to an unexpected database")
        if urlsplit(identity_url).path != "/woori_blog_agent":
            fail("Existing operations identity does not point to the project database")
    else:
        passwords = {role: secrets.token_urlsafe(36) for role in (OWNER, APP, READER, IDENTITY)}
        for role in (OWNER, APP, READER, IDENTITY):
            admin.execute(sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(passwords[role])))
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(DB), sql.Identifier(OWNER)))
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DB)))
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {},{}").format(
            sql.Identifier(DB), sql.Identifier(APP), sql.Identifier(READER)))
        def make_url(role: str, password: str, database: str) -> str:
            from urllib.parse import quote
            return f"postgresql://{role}:{quote(password, safe='')}@127.0.0.1:5432/{database}"
        migration_url = make_url(OWNER, passwords[OWNER], DB)
        app_url = make_url(APP, passwords[APP], DB)
        reader_url = make_url(READER, passwords[READER], DB)
        identity_url = make_url(IDENTITY, passwords[IDENTITY], "woori_blog_agent")
        role_files["migration"].write_text(f"MIGRATION_DATABASE_URL={migration_url}\n", encoding="utf-8")
        role_files["application"].write_text(
            f"DATABASE_URL={app_url}\nWOORI_OPERATION_DATABASE_URL={identity_url}\n", encoding="utf-8")
        role_files["reader"].write_text(f"EVALUATION_DATABASE_URL={reader_url}\n", encoding="utf-8")
    # This identity can connect to operations solely to compare current_database().
    admin.execute("GRANT CONNECT ON DATABASE woori_blog_agent TO woori_eval_identity")

source_args, source_env = pg_args(ops_url)
target_args, target_env = pg_args(migration_url)
archive = None
archives = sorted((ROOT / "backups").glob("evaluation_snapshot_*.dump"), key=lambda item: item.stat().st_mtime)
if archives:
    archive = archives[-1]
else:
    archive = ROOT / "backups" / (
        f"evaluation_snapshot_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}.dump")
    archive.parent.mkdir(exist_ok=True)
with psycopg.connect(migration_url) as evaluation:
    installed = evaluation.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
    schema_version = evaluation.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] if installed else 0
if schema_version == 0:
    if archive.stat().st_size == 0:
        fail("Evaluation snapshot archive is empty")
    restore_args = [str(BIN / "pg_restore.exe"), *target_args, "--dbname", DB, "--no-owner", "--no-acl",
                    "--exit-on-error", "--single-transaction", str(archive)]
    restore = subprocess.run(restore_args, env=target_env, capture_output=True, check=False, timeout=600)
    if restore.returncode:
        fail("Evaluation snapshot restore failed; the new evaluation database was retained for inspection")
    schema_version = 24
elif schema_version != 24:
    fail("The existing evaluation database is partially migrated; refusing to overwrite it")

with psycopg.connect(migration_url, row_factory=psycopg.rows.dict_row) as evaluation:
    evaluation.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    evaluation.execute("GRANT USAGE ON SCHEMA public TO woori_eval_app,woori_eval_reader")
    evaluation.execute("GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA public TO woori_eval_app")
    evaluation.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO woori_eval_app")
    evaluation.execute("""GRANT SELECT ON job_runs,generation_jobs,generation_targets,generation_results,
        generation_stage_runs,evidence_facts,research_sources,source_reviews,language_profiles,
        languages,generation_settings,content_versions,prompt_templates,audit_events,worker_heartbeats TO woori_eval_reader""")
    quarantined = evaluation.execute(
        """UPDATE job_runs SET status='failed',lease_until=NULL,error_type='evaluation_snapshot_quarantined',
        error_message='Copied active work is quarantined in the evaluation snapshot',
        resolution='Not resumed in isolated evaluation'
        WHERE task_kind='content' AND status IN ('queued','running') RETURNING id"""
    ).fetchall()
    evaluation.execute("UPDATE generation_jobs SET paused=true WHERE run_id=ANY(%s)",
                       ([r["id"] for r in quarantined],))
    evaluation.execute("UPDATE pipeline_controls SET evaluation_isolated=true WHERE singleton=true")
    evaluation.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES ('evaluation.environment.initialized',%s)",
        (Jsonb({"snapshot_archive": archive.name, "source_schema_version": schema_version,
          "excluded_sensitive_tables": list(EXCLUDED_DATA),
          "quarantined_active_jobs": len(quarantined)}),),
    )
    counts = evaluation.execute(
        """SELECT (SELECT count(*) FROM google_connections) oauth_connections,
        (SELECT count(*) FROM google_oauth_states) oauth_states,
        (SELECT count(*) FROM blogger_blogs) blogger_rows,
        (SELECT count(*) FROM publishing_policies WHERE auto_publish_allowed) auto_publish_rows,
        (SELECT count(*) FROM language_execution_limits WHERE publishing_enabled) publishing_enabled_rows,
        (SELECT count(*) FROM research_sources WHERE valid_until>now()) current_sources,
        (SELECT count(*) FROM source_reviews WHERE approved) approved_reviews,
        (SELECT count(*) FROM schema_migrations) migrations"""
    ).fetchone()
    if any(counts[k] for k in (
        "oauth_connections", "oauth_states", "blogger_rows", "auto_publish_rows", "publishing_enabled_rows"
    )):
        fail("Evaluation clone contains OAuth/Blogger/publishing data; it remains disabled")
    evaluation.commit()

print({"evaluation_database": DB, "roles_created": [OWNER, APP, READER, IDENTITY],
       "schema_version": schema_version, "snapshot_archive": str(archive.relative_to(ROOT)),
       "quarantined_active_content_jobs": len(quarantined), "verified_counts": dict(counts),
       "credentials_written_to_ignored_env_files": True})
