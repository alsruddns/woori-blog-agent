"""Read-only reconciliation of an uncertain Trends LIVE write with a known ID."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from . import blogger_service, external_policy
from .blogger_writes import BloggerLivePublisher
from .db import connection
from .google_http import GoogleFailure, numeric_id
from .trends_publication import validate_trends_job


def verify_trends_live_readback(
    *, ledger: dict[str, Any], expected: dict[str, Any], remote: dict[str, Any]
) -> None:
    """Require the original POST fingerprint and the same exact remote article."""
    result = ledger.get("result") or {}
    if (ledger.get("operation") != "create_live" or ledger.get("status") != "uncertain"
            or result.get("status") != "LIVE" or result.get("http_status") not in {200, 201}
            or result.get("readback_verified") is not False):
        raise GoogleFailure("reconciliation_ledger_not_eligible")
    post_id = numeric_id(str(result.get("post_id") or ""))
    blog_id = numeric_id(str(result.get("blog_id") or ""))
    labels = list(expected.get("labels") or [])
    payload: dict[str, Any] = {"title": expected.get("title"), "content": expected.get("html")}
    if labels:
        payload["labels"] = labels
    if (not payload["title"] or not payload["content"]
            or BloggerLivePublisher._fingerprint("create_live", blog_id, payload)
            != ledger.get("request_fingerprint")):
        raise GoogleFailure("reconciliation_original_payload_mismatch")
    remote_labels = remote.get("labels") or []
    remote_blog = remote.get("blog")
    if (str(remote.get("id")) != post_id or not isinstance(remote_blog, dict)
            or str(remote_blog.get("id")) != blog_id
            or remote.get("status") != "LIVE" or remote.get("title") != payload["title"]
            or remote.get("content") != payload["content"]
            or not isinstance(remote_labels, list) or not all(isinstance(x, str) for x in remote_labels)
            or not all(isinstance(x, str) for x in labels) or sorted(remote_labels) != sorted(labels)
            or not isinstance(remote.get("url"), str) or not remote["url"].startswith("https://")
            or remote.get("url") != result.get("url") or not isinstance(remote.get("published"), str)):
        raise GoogleFailure("reconciliation_remote_payload_mismatch")
    try:
        published = datetime.fromisoformat(remote["published"])
        original = datetime.fromisoformat(str(result["published_at"]))
        if published.utcoffset() is None or original.utcoffset() is None or published != original:
            raise ValueError("published_time_mismatch")
    except (KeyError, ValueError):
        raise GoogleFailure("reconciliation_published_time_mismatch") from None


def reconcile_uncertain_trends_live(job_id: UUID) -> dict[str, Any]:
    """Read the exact existing post once; atomically reconcile only an exact match.

    This never sends a Blogger write, retries an ambiguous POST, or requeues jobs.
    """
    if external_policy.billing_credential_names():
        raise GoogleFailure("billable_credentials_present")
    key = "live:pubjob-" + str(job_id) + "-publish"
    with connection() as conn:
        quota = conn.execute("""SELECT
            max(id) FILTER (WHERE event_type='external.call.quota_stopped') AS last_quota,
            max(id) FILTER (WHERE event_type='external.call.completed'
                AND payload->>'operation'='blogger_read' AND payload->>'status'='200') AS last_read
            FROM audit_events WHERE payload->>'provider'='google_blogger_read'
              AND event_type IN ('external.call.quota_stopped','external.call.completed')""").fetchone()
        if (not quota or (quota["last_quota"] is not None
                          and (quota["last_read"] is None or quota["last_read"] <= quota["last_quota"]))):
            raise GoogleFailure("reconciliation_waiting_for_free_quota_recovery")
        job = conn.execute("SELECT * FROM publishing_jobs WHERE id=%s", (job_id,)).fetchone()
        ledger = conn.execute("SELECT * FROM blogger_write_operations WHERE idempotency_key=%s", (key,)).fetchone()
        if (not job or job["publication_lane"] != "trends_auto" or job["status"] != "uncertain"
                or job["adapter_type"] != "blogger_live" or job["simulation_only"] or not ledger):
            raise GoogleFailure("reconciliation_job_not_eligible")
        checked = validate_trends_job(conn, job["blog_id"], job["content_version_id"])
        row = checked.get("row")
        result = ledger.get("result") or {}
        if (not row or str(row["blog_id"]) != str(result.get("blog_id"))
                or str(job["oauth_connection_id"]) != str(result.get("connection_id"))):
            raise GoogleFailure("reconciliation_origin_or_target_mismatch")
        expected = {"title": row["title"], "html": row["safe_html"], "labels": row["blogger_labels"]}
        # Verify the immutable original request fingerprint before any network call.
        payload: dict[str, Any] = {"title": expected["title"], "content": expected["html"]}
        if expected["labels"]:
            payload["labels"] = expected["labels"]
        if (ledger["status"] != "uncertain" or ledger["operation"] != "create_live"
                or result.get("status") != "LIVE" or result.get("http_status") not in {200, 201}
                or result.get("readback_verified") is not False
                or BloggerLivePublisher._fingerprint("create_live", str(result.get("blog_id") or ""), payload)
                != ledger["request_fingerprint"]):
            raise GoogleFailure("reconciliation_original_payload_mismatch")
        post_id = numeric_id(str(result.get("post_id") or ""))

    remote = blogger_service.post(job["blog_id"], post_id)
    verify_trends_live_readback(ledger=ledger, expected=expected, remote=remote)
    verified_result = {**result, "readback_verified": True, "reconciled_readback": True,
                       "readback_http_status": 200}
    with connection() as conn:
        conn.execute("SET LOCAL lock_timeout='3s'")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("blogger-global-publication-write",))
        current_job = conn.execute("SELECT * FROM publishing_jobs WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
        current_ledger = conn.execute("SELECT * FROM blogger_write_operations WHERE idempotency_key=%s FOR UPDATE", (key,)).fetchone()
        current_blog = conn.execute("SELECT blog_id,oauth_connection_id FROM blogger_blogs WHERE id=%s", (job["blog_id"],)).fetchone()
        if (not current_job or current_job["status"] != "uncertain"
                or current_job["blog_id"] != job["blog_id"]
                or current_job["content_version_id"] != job["content_version_id"]
                or not current_ledger or current_ledger["status"] != "uncertain"
                or current_ledger["request_fingerprint"] != ledger["request_fingerprint"]
                or current_ledger["result"] != result or not current_blog
                or str(current_blog["blog_id"]) != str(result["blog_id"])
                or str(current_blog["oauth_connection_id"]) != str(result["connection_id"])):
            raise GoogleFailure("reconciliation_state_changed")
        conn.execute("""INSERT INTO publishing_records(job_id,blog_id,content_version_id,remote_post_id,
            published_at,remote_url,remote_status,remote_verified_at)
            VALUES (%s,%s,%s,%s,%s,%s,'LIVE',now()) ON CONFLICT DO NOTHING""",
            (job_id, job["blog_id"], job["content_version_id"], post_id, remote["published"], remote["url"]))
        record = conn.execute("SELECT id,job_id,remote_post_id,remote_url FROM publishing_records WHERE blog_id=%s AND content_version_id=%s",
                              (job["blog_id"], job["content_version_id"])).fetchone()
        if not record or record["job_id"] != job_id or record["remote_post_id"] != post_id or record["remote_url"] != remote["url"]:
            raise GoogleFailure("published_record_conflict")
        conn.execute("UPDATE blogger_write_operations SET status='succeeded',result=%s WHERE idempotency_key=%s",
                     (Jsonb(verified_result), key))
        conn.execute("""UPDATE publishing_jobs SET status='succeeded',publication_state='published',
            live_stage='published',remote_post_id=%s,lease_until=NULL,last_error_category=NULL,updated_at=now()
            WHERE id=%s""", (post_id, job_id))
        conn.execute("UPDATE post_publication_reviews SET publishing_record_id=%s,post_id=%s,updated_at=now() WHERE publishing_job_id=%s AND publishing_record_id IS NULL",
                     (record["id"], post_id, job_id))
        conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                     ("publication.trends_auto.live_reconciled", Jsonb({"job_id": str(job_id),
                      "post_id": post_id, "remote_readback_verified": True, "blogger_write_performed": False})))
    return {"job_id": str(job_id), "post_id": post_id, "status": "published", "blogger_write_performed": False}
