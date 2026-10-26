"""Restore into a new, owned temporary database, then remove only that database."""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
from dotenv import dotenv_values
from psycopg import sql

root = Path(__file__).resolve().parents[1]
owner_url = dotenv_values(root / ".env.migration")["MIGRATION_DATABASE_URL"]
parsed = urlsplit(owner_url)
if parsed.path != "/woori_blog_agent":
    raise SystemExit("Refusing non-project source")
target = "woori_blog_agent_restore_" + datetime.now(UTC).strftime("%Y%m%d") + "_" + uuid4().hex[:8]
if not target.startswith("woori_blog_agent_restore_") or target == "woori_blog_agent":
    raise SystemExit("Unsafe restore target")
folder = root / "backups"
folder.mkdir(exist_ok=True)
archive = folder / (target + ".dump")
bin_dir = Path("C:/Program Files/PostgreSQL/16/bin")
env = {**os.environ, "PGPASSWORD": unquote(parsed.password or "")}
args = [
    "-h",
    parsed.hostname or "localhost",
    "-p",
    str(parsed.port or 5432),
    "-U",
    parsed.username or "",
]
created = False
try:
    with psycopg.connect(owner_url) as source:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        schema_version = source.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        tables = [
            "content_versions",
            "audit_events",
            "blogger_blogs",
            "google_connections",
            "keyword_candidates",
            "research_sources",
            "source_reviews",
            "generation_results",
            "generation_targets",
            "research_dispatches",
            "collection_sources",
            "collection_items",
            "model_measurements",
        ]
        counts = {
            table: source.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in tables
        }
        snapshot = source.execute("SELECT pg_export_snapshot()").fetchone()[0]
        result = subprocess.run(
            [
                str(bin_dir / "pg_dump.exe"),
                *args,
                "-d",
                "woori_blog_agent",
                "-Fc",
                "--snapshot",
                snapshot,
                "-f",
                str(archive),
            ],
            env=env,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit("Snapshot backup failed")
    with psycopg.connect("postgresql://postgres@localhost:5432/postgres", autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone():
            raise SystemExit("Restore target already exists; refusing")
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER woori_owner").format(sql.Identifier(target))
        )
        created = True
        admin.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target))
        )
    result = subprocess.run(
        [
            str(bin_dir / "pg_restore.exe"),
            *args,
            "-d",
            target,
            "--exit-on-error",
            "--no-owner",
            str(archive),
        ],
        env=env,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit("Isolated restore failed")
    with psycopg.connect(owner_url, dbname=target) as restored:
        assert (
            restored.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            == schema_version
        )
        for table, count in counts.items():
            assert (
                restored.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                == count
            )
        try:
            with restored.transaction():
                restored.execute("UPDATE audit_events SET event_type=event_type")
        except psycopg.Error:
            pass
        else:
            raise SystemExit("Restored audit immutability check failed")
    print(
        "Isolated restore verified: schema", schema_version, "snapshot counts and audit protection."
    )
finally:
    if created:
        with psycopg.connect(
            "postgresql://postgres@localhost:5432/postgres", autocommit=True
        ) as admin:
            owner = admin.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (target,)
            ).fetchone()
            if (
                target.startswith("woori_blog_agent_restore_")
                and owner
                and owner[0] == "woori_owner"
            ):
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))
                print(
                    "Owned temporary restore database removed; original database was not overwritten."
                )

from woori.db import connection

with connection() as audit_db:
    audit_db.execute(
        "INSERT INTO audit_events(event_type,payload) VALUES ('operations.restore.completed',jsonb_build_object('schema_version',%s,'isolated',true))",
        (schema_version,),
    )
