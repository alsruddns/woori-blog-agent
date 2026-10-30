import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
MAX_SUPPORTED_SCHEMA_VERSION = 67
parser = argparse.ArgumentParser()
parser.add_argument("--status", action="store_true", help="Read-only operations schema version check")
args = parser.parse_args()
url = (
    os.environ.get("MIGRATION_DATABASE_URL")
    or dotenv_values(root / ".env.migration")["MIGRATION_DATABASE_URL"]
)
with psycopg.connect(url) as conn:
    if conn.info.dbname != "woori_blog_agent":
        raise SystemExit("Refusing non-project database")
    if args.status:
        conn.execute("SET TRANSACTION READ ONLY")
        exists = conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
        version = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] if exists else 0
        print(json.dumps({"database": conn.info.dbname, "schema_version": version or 0}))
        raise SystemExit(0)
    conn.execute("SELECT pg_advisory_xact_lock(813219)")
    exists = conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
    if not exists:
        conn.execute((root / "scripts/001_initial.sql").read_text(), prepare=False)
    current = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    if current > MAX_SUPPORTED_SCHEMA_VERSION:
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
    if current < 15:
        conn.execute(
            (root / "scripts/015_research_experiment_evaluations.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 16:
        conn.execute(
            (root / "scripts/016_evidence_localization.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 17:
        conn.execute(
            (root / "scripts/017_reviewed_source_language.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 18:
        conn.execute(
            (root / "scripts/018_glossary_revision_backfill.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 19:
        conn.execute(
            (root / "scripts/019_full_article_evaluations.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 20:
        conn.execute(
            (root / "scripts/020_article_keywords.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 21:
        conn.execute(
            (root / "scripts/021_parse_failure_artifacts.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 22:
        conn.execute(
            (root / "scripts/022_fact_registry_stage.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 23:
        conn.execute(
            (root / "scripts/023_worker_heartbeats.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 24:
        conn.execute(
            (root / "scripts/024_evaluation_isolation_quotas.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 25:
        conn.execute(
            (root / "scripts/025_publication_safety.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 26:
        conn.execute(
            (root / "scripts/026_publication_scheduling.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 27:
        conn.execute(
            (root / "scripts/027_article_human_reviews.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 28:
        conn.execute(
            (root / "scripts/028_editorial_review_decision.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 29:
        conn.execute(
            (root / "scripts/029_editorial_versions_and_progress.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 30:
        conn.execute(
            (root / "scripts/030_manuscript_editing_metadata.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 31:
        conn.execute(
            (root / "scripts/031_editorial_existing_post_link.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 32:
        conn.execute(
            (root / "scripts/032_editorial_base_hash.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 33:
        conn.execute(
            (root / "scripts/033_publication_approval.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 34:
        conn.execute(
            (root / "scripts/034_oauth_write_scope.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 35:
        conn.execute(
            (root / "scripts/035_trend_observations.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 36:
        conn.execute(
            (root / "scripts/036_trend_call_quota.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 37:
        conn.execute(
            (root / "scripts/037_trend_topics_and_packages.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 38:
        conn.execute(
            (root / "scripts/038_trend_http_status.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 39:
        conn.execute(
            (root / "scripts/039_trend_grouping_reviews.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 40:
        conn.execute(
            (root / "scripts/040_research_package_review_state.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 41:
        conn.execute(
            (root / "scripts/041_editorial_seo_metadata.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 42:
        conn.execute(
            (root / "scripts/042_publication_modes.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 43:
        conn.execute(
            (root / "scripts/043_localized_publication_requests.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 44:
        conn.execute(
            (root / "scripts/044_localized_request_recovery.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 45:
        conn.execute(
            (root / "scripts/045_external_content_imports.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 46:
        conn.execute(
            (root / "scripts/046_trend_topic_categories.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 47:
        conn.execute(
            (root / "scripts/047_import_review_pipeline.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 48:
        conn.execute(
            (root / "scripts/048_import_content_version_bridge.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 49:
        conn.execute(
            (root / "scripts/049_blogger_live_publication_queue.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 50:
        conn.execute(
            (root / "scripts/050_trends_eleven_geographies.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 51:
        conn.execute(
            (root / "scripts/051_trend_approx_traffic.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 52:
        conn.execute(
            (root / "scripts/052_scheduled_publication_approval.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 53:
        conn.execute(
            (root / "scripts/053_post_publication_review.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 54:
        conn.execute(
            (root / "scripts/054_post_publication_content_identity.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 55:
        conn.execute(
            (root / "scripts/055_scheduled_prepublication_reviews.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 56:
        conn.execute(
            (root / "scripts/056_manual_publication_approval.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 57:
        conn.execute(
            (root / "scripts/057_manual_publication_reason_length.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 58:
        conn.execute(
            (root / "scripts/058_publication_worker_mode.sql").read_text(encoding="utf-8"),
            prepare=False,
        )
    if current < 59:
        conn.execute((root / 'scripts/059_verified_publication_record_insert.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 60:
        conn.execute((root / 'scripts/060_entertainment_category.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 61:
        conn.execute((root / 'scripts/061_codex_authoring_jobs.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 62:
        conn.execute((root / 'scripts/062_trend_editorial_queue.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 63:
        conn.execute((root / 'scripts/063_trend_codex_provenance.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 64:
        conn.execute((root / 'scripts/064_trend_collection_settings.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 65:
        conn.execute((root / 'scripts/065_trend_blog_geo_authoring.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 66:
        conn.execute((root / 'scripts/066_sports_editorial_category.sql').read_text(encoding='utf-8'), prepare=False)
    if current < 67:
        conn.execute((root / 'scripts/067_trends_publication_policy.sql').read_text(encoding='utf-8'), prepare=False)
print("Project migrations through 067 verified")
