from contextlib import contextmanager
from copy import deepcopy

import pytest
from psycopg.types.json import Jsonb
from test_automation_controls import center, lab, make_job  # noqa: F401
from woori import publication_reconciliation as reconciliation
from woori.blogger_writes import BloggerLivePublisher
from woori.google_http import GoogleFailure
from woori.publication_reconciliation import verify_trends_live_readback


def _evidence():
    expected = {"title": "Article title", "html": "<p>Original article.</p>", "labels": ["B", "A"]}
    result = {"post_id": "12345", "blog_id": "67890", "status": "LIVE", "http_status": 200,
              "readback_verified": False, "url": "https://example.blogspot.com/post",
              "published_at": "2026-11-24T00:23:52+09:00"}
    ledger = {"operation": "create_live", "status": "uncertain", "result": result,
              "request_fingerprint": BloggerLivePublisher._fingerprint("create_live", "67890",
                  {"title": expected["title"], "content": expected["html"], "labels": expected["labels"]})}
    remote = {"id": "12345", "blog": {"id": "67890"}, "status": "LIVE", "title": expected["title"],
              "content": expected["html"], "labels": ["A", "B"], "url": result["url"],
              "published": result["published_at"]}
    return ledger, expected, remote


def test_exact_existing_live_post_can_be_reconciled_without_reposting():
    ledger, expected, remote = _evidence()
    verify_trends_live_readback(ledger=ledger, expected=expected, remote=remote)


@pytest.mark.parametrize("field,value", [
    ("id", "99999"), ("blog", {"id": "99999"}), ("status", "DRAFT"),
    ("title", "Changed title"), ("content", "<p>Changed</p>"), ("labels", ["other"]),
    ("url", "https://example.blogspot.com/other"), ("published", "2026-11-23T00:23:52+09:00"),
])
def test_changed_remote_post_is_never_reconciled(field, value):
    ledger, expected, remote = _evidence()
    remote[field] = value
    with pytest.raises(GoogleFailure, match="reconciliation_"):
        verify_trends_live_readback(ledger=ledger, expected=expected, remote=remote)


def test_unverified_or_changed_original_request_is_rejected():
    ledger, expected, remote = _evidence()
    changed = deepcopy(expected)
    changed["html"] = "<p>Different version.</p>"
    with pytest.raises(GoogleFailure, match="reconciliation_original_payload_mismatch"):
        verify_trends_live_readback(ledger=ledger, expected=changed, remote=remote)
    ledger["result"]["http_status"] = None
    with pytest.raises(GoogleFailure, match="reconciliation_ledger_not_eligible"):
        verify_trends_live_readback(ledger=ledger, expected=expected, remote=remote)


def test_reconciliation_never_retries_an_unrecovered_quota(center, monkeypatch):  # noqa: F811
    from uuid import uuid4

    conn, _, _ = center
    @contextmanager
    def shared():
        with conn.transaction():
            yield conn
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES (%s,%s)",
                 ("external.call.quota_stopped", Jsonb({"provider": "google_blogger_read"})))
    monkeypatch.setattr(reconciliation, "connection", shared)
    monkeypatch.setattr(reconciliation.external_policy, "billing_credential_names", list)
    monkeypatch.setattr(reconciliation.blogger_service, "post", lambda *_: pytest.fail("quota was retried"))
    with pytest.raises(GoogleFailure, match="reconciliation_waiting_for_free_quota_recovery"):
        reconciliation.reconcile_uncertain_trends_live(uuid4())


def test_reconciliation_blocks_billable_credentials_before_any_remote_read(monkeypatch):
    from uuid import uuid4

    monkeypatch.setattr(reconciliation.external_policy, "billing_credential_names", lambda: ["OPENAI_API_KEY"])
    monkeypatch.setattr(reconciliation.blogger_service, "post", lambda *_: pytest.fail("unexpected remote read"))
    with pytest.raises(GoogleFailure, match="billable_credentials_present"):
        reconciliation.reconcile_uncertain_trends_live(uuid4())


@pytest.mark.parametrize("matches", [True, False])
def test_reconciliation_updates_only_an_exact_known_live_post(center, monkeypatch, matches):  # noqa: F811
    conn, _, _ = center
    job_id, _blog_id, _version_id = make_job(center, lane="trends_auto", method="codex_trends_export")
    ledger, expected, remote = _evidence()
    job = conn.execute("SELECT oauth_connection_id FROM publishing_jobs WHERE id=%s", (job_id,)).fetchone()
    real_blog = "1234567890123456"
    ledger["result"]["blog_id"] = real_blog
    ledger["result"]["connection_id"] = str(job["oauth_connection_id"])
    remote["blog"]["id"] = real_blog
    ledger["request_fingerprint"] = BloggerLivePublisher._fingerprint("create_live", real_blog,
        {"title": expected["title"], "content": expected["html"], "labels": expected["labels"]})
    if not matches:
        remote["content"] = "<p>changed</p>"
    key = "live:pubjob-" + str(job_id) + "-publish"
    conn.execute("UPDATE publishing_jobs SET status='uncertain',publication_state='publication_failed' WHERE id=%s", (job_id,))
    conn.execute("INSERT INTO blogger_write_operations(idempotency_key,request_fingerprint,operation,status,result) VALUES(%s,%s,'create_live','uncertain',%s)",
                 (key, ledger["request_fingerprint"], Jsonb(ledger["result"])))
    @contextmanager
    def shared():
        with conn.transaction():
            yield conn
    monkeypatch.setattr(reconciliation, "connection", shared)
    monkeypatch.setattr(reconciliation.external_policy, "billing_credential_names", list)
    monkeypatch.setattr(reconciliation, "validate_trends_job", lambda *_: {"row": {
        "blog_id": real_blog, "title": expected["title"], "safe_html": expected["html"],
        "blogger_labels": expected["labels"],
    }})
    monkeypatch.setattr(reconciliation.blogger_service, "post", lambda *_: remote)
    if matches:
        result = reconciliation.reconcile_uncertain_trends_live(job_id)
        assert result["status"] == "published" and result["blogger_write_performed"] is False
        assert conn.execute("SELECT status FROM blogger_write_operations WHERE idempotency_key=%s", (key,)).fetchone()["status"] == "succeeded"
        assert conn.execute("SELECT remote_status FROM publishing_records WHERE job_id=%s", (job_id,)).fetchone()["remote_status"] == "LIVE"
    else:
        with pytest.raises(GoogleFailure, match="reconciliation_remote_payload_mismatch"):
            reconciliation.reconcile_uncertain_trends_live(job_id)
        assert conn.execute("SELECT status FROM blogger_write_operations WHERE idempotency_key=%s", (key,)).fetchone()["status"] == "uncertain"
        assert not conn.execute("SELECT 1 FROM publishing_records WHERE job_id=%s", (job_id,)).fetchone()
