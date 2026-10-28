"""Grant the isolated reader only the evaluation tables needed by review UIs."""

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
    tables = ("article_quality_evaluations", "research_experiment_evaluations")
    changed: list[str] = []
    for table in tables:
        if not conn.execute(
            "SELECT to_regclass(%s) AS table_name", (f"public.{table}",)
        ).fetchone()["table_name"]:
            raise SystemExit(f"Evaluation read table is missing: {table}")
        allowed = conn.execute(
            "SELECT has_table_privilege('woori_eval_reader',%s,'SELECT') AS allowed", (table,)
        ).fetchone()["allowed"]
        if not allowed:
            # Table names come only from the fixed allowlist above.
            conn.execute(f"GRANT SELECT ON {table} TO woori_eval_reader")
            changed.append(table)
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('evaluation.reader_access.granted',%s)",
                (Jsonb({"role": "woori_eval_reader", "table": table, "privilege": "SELECT"}),),
            )
    conn.commit()
    for table in tables:
        allowed = conn.execute(
            "SELECT has_table_privilege('woori_eval_reader',%s,'SELECT') AS allowed", (table,)
        ).fetchone()["allowed"]
        if not allowed:
            raise SystemExit(f"Read-only evaluation access grant verification failed: {table}")
    print({"database": identity["name"], "privileges": {table: "SELECT" for table in tables}, "changed_tables": changed})
