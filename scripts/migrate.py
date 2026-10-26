from pathlib import Path

import psycopg
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
url = dotenv_values(root / ".env.migration")["MIGRATION_DATABASE_URL"]
with psycopg.connect(url) as conn:
    if conn.info.dbname != "woori_blog_agent":
        raise SystemExit("Refusing non-project database")
    conn.execute("SELECT pg_advisory_xact_lock(813219)")
    exists = conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
    if not exists:
        conn.execute((root / "scripts/001_initial.sql").read_text(), prepare=False)
    current = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    if current > 4:
        raise SystemExit("Database schema is newer than this application")
    if current < 2:
        conn.execute(
            (root / "scripts/002_multilingual.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 3:
        conn.execute(
            (root / "scripts/003_reference_guards.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 4:
        conn.execute(
            (root / "scripts/004_config_permissions.sql").read_text(encoding="utf-8"), prepare=False
        )
print("Migration 004 verified")
