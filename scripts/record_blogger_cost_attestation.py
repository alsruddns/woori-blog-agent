"""Record the project owner's Blogger-only zero-cost attestation append-only."""

from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from woori.config import settings
from woori.db import connection
from woori.external_policy import (
    BLOGGER_APPROVAL_EVENT,
    BLOGGER_APPROVAL_SCOPE,
    BLOGGER_REVOCATION_EVENT,
    billing_credential_names,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--attestation",
        required=True,
        choices=["PROJECT_OWNER_CONFIRMS_BLOGGER_API_ZERO_COST"],
        help="Explicit confirmation already supplied by the project owner.",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=True)
    settings.cache_clear()
    if billing_credential_names():
        raise SystemExit(
            "Refusing Blogger attestation while potentially billable credentials are configured"
        )
    with connection() as conn:
        identity = conn.execute(
            "SELECT current_database() AS db,current_user AS role,inet_server_addr()::text AS address"
        ).fetchone()
        if not identity or identity["db"] != "woori_blog_agent" or identity["role"] != "woori_app":
            raise SystemExit(
                "Refusing to record owner attestation outside the local operations database"
            )
        host = str(identity["address"] or "").split("/", 1)[0]
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise SystemExit("Refusing non-local operations database")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('blogger-cost-policy',0))")
        latest = conn.execute(
            """SELECT event_type,payload,created_at FROM audit_events
            WHERE event_type IN (%s,%s) AND payload->>'provider'='google_blogger_read'
            ORDER BY id DESC LIMIT 1""",
            (BLOGGER_APPROVAL_EVENT, BLOGGER_REVOCATION_EVENT),
        ).fetchone()
        if latest and latest["event_type"] == BLOGGER_APPROVAL_EVENT:
            print("Blogger-only cost attestation already active; no duplicate event written.")
            return
        approval_id = str(uuid4())
        conn.execute(
            """INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)""",
            (
                BLOGGER_APPROVAL_EVENT,
                Jsonb(
                    {
                        "approval_id": approval_id,
                        "provider": "google_blogger_read",
                        "policy_version": 1,
                        "actor": "project_owner_attestation_from_user_instruction",
                        "evidence": args.attestation,
                        "approved_scope": sorted(BLOGGER_APPROVAL_SCOPE),
                        "before": {
                            "zero_cost_reviewed": False,
                            "calls_allowed": False,
                            "block_reason": "manual_zero_cost_review_required",
                        },
                        "after": {
                            "zero_cost_reviewed": True,
                            "provider_scope_only": "google_blogger_read",
                            "approved_operations": sorted(BLOGGER_APPROVAL_SCOPE),
                            "methods": [
                                "GET",
                                "POST-private-draft-only",
                                "PATCH/PUT-user-approved-update",
                            ],
                            "delete_allowed": False,
                            "publish_or_schedule_allowed": False,
                            "automatic_publishing_allowed": False,
                        },
                        "other_provider_cost_gates_changed": False,
                    }
                ),
            ),
        )
    print(f"Recorded Blogger-only owner cost attestation: {approval_id}")


if __name__ == "__main__":
    try:
        main()
    except (psycopg.Error, OSError) as exc:
        raise SystemExit(f"Could not record Blogger attestation: {type(exc).__name__}") from None
