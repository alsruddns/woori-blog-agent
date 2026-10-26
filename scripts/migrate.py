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
    if current > 14:
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
    if current < 5:
        conn.execute(
            (root / "scripts/005_blogger_oauth.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 6:
        conn.execute(
            (root / "scripts/006_content_categories.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 7:
        conn.execute(
            (root / "scripts/007_research_pipeline.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 8:
        conn.execute(
            (root / "scripts/008_research_dispatch.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 9:
        conn.execute(
            (root / "scripts/009_pipeline_permissions.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 10:
        conn.execute(
            (root / "scripts/010_review_order.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 11:
        conn.execute(
            (root / "scripts/011_live_research.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 12:
        conn.execute(
            (root / "scripts/012_source_revisions.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 13:
        conn.execute(
            (root / "scripts/013_evaluation_jobs.sql").read_text(encoding="utf-8"), prepare=False
        )
    if current < 14:
        conn.execute(
            (root / "scripts/014_generation_stages.sql").read_text(encoding="utf-8"), prepare=False
        )
print("Migration 014 verified")
