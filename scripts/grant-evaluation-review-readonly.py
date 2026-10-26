"""Grant the isolated review reader SELECT on quality evaluation records only."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
url = os.environ.get("EVALUATION_MIGRATION_DATABASE_URL") or dotenv_values(
    ROOT / ".env.evaluation-migration"
).get("MIGRATION_DATABASE_URL")
if not url:
    raise SystemExit("Evaluation migration connection is not configured")

with psycopg.connect(url, row_factory=psycopg.rows.dict_row) as conn:
    identity = conn.execute(
        "SELECT current_database() AS name,inet_server_addr()::text AS address"
    ).fetchone()
    if (
        not identity
        or identity["name"] != "woori_blog_agent_eval"
        or identity["address"].split("/")[0] not in {"127.0.0.1", "::1"}
    ):
        raise SystemExit("Refusing review-reader privilege change outside the local evaluation database")
    if not conn.execute("SELECT to_regclass('public.article_quality_evaluations') AS table_name").fetchone()["table_name"]:
        raise SystemExit("Evaluation quality table is missing")
    was_granted = conn.execute(
        "SELECT has_table_privilege('woori_eval_reader','article_quality_evaluations','SELECT') AS allowed"
    ).fetchone()["allowed"]
    if not was_granted:
        conn.execute("GRANT SELECT ON article_quality_evaluations TO woori_eval_reader")
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('evaluation.reader_access.granted',%s)",
            (Jsonb({"role": "woori_eval_reader", "table": "article_quality_evaluations", "privilege": "SELECT"}),),
        )
    conn.commit()
    allowed = conn.execute(
        "SELECT has_table_privilege('woori_eval_reader','article_quality_evaluations','SELECT') AS allowed"
    ).fetchone()["allowed"]
    if not allowed:
        raise SystemExit("Read-only evaluation access grant verification failed")
    print({"database": identity["name"], "table": "article_quality_evaluations", "privilege": "SELECT", "already_granted": was_granted})
