import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from test_pipeline import lab as shared_lab

lab = shared_lab
from woori import collection, external_policy
from woori.ai import Draft, EngineFailure
from woori.grounding import inspect
from woori.local_inference import LlamaCppProvider


def test_external_policy_closed_allowlist_and_zero_cost_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(external_policy.ExternalCallBlocked, match="provider_not_allowlisted"):
        external_policy.client("unknown_provider", "anything")
    with pytest.raises(external_policy.ExternalCallBlocked, match="provider_not_allowlisted"):
        external_policy.client("google_blogger_read", "post_write")

    monkeypatch.setattr(external_policy, "billing_credential_names", lambda: ["OPENAI_API_KEY"])
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    assert external_policy.status()["external_calls_allowed"] is False
    assert external_policy.status()["blocked_credential_names"] == ["OPENAI_API_KEY"]
    with pytest.raises(
        external_policy.ExternalCallBlocked,
        match="potentially_billable_credentials_detected",
    ):
        external_policy._authorize(
            "federal_reserve", "source_collection", httpx.Request(
                "GET", "https://www.federalreserve.gov/feeds/press_all.xml"
            )
        )


def test_external_policy_blocks_unlisted_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    with pytest.raises(
        external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"
    ):
        external_policy._authorize(
            "google_blogger_read", "blogger_read",
            httpx.Request("GET", "https://example.com/blogger/v3/blogs/1"),
        )
    with pytest.raises(
        external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"
    ):
        external_policy._authorize(
            "artifact_setup", "artifact_download",
            httpx.Request("GET", "https://api.github.com/repos/other/project/releases"),
        )


def test_blogger_reads_wait_for_manual_zero_cost_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    policy = external_policy.status()
    blogger = next(p for p in policy["providers"] if p["name"] == "google_blogger_read")
    assert blogger["calls_allowed"] is False
    assert blogger["block_reason"] == "manual_zero_cost_review_required"
    transport = external_policy.guarded_transport(
        "google_blogger_read",
        "blogger_read",
        httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    )
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(external_policy.ExternalCallBlocked, match="provider_cost_unverified"),
    ):
        client.get("https://www.googleapis.com/blogger/v3/blogs/123")


@pytest.mark.parametrize("status", [429, 403])
def test_external_policy_quota_is_a_hard_stop(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    if status == 429:
        handler = lambda request: httpx.Response(429, request=request)
    else:
        handler = lambda request: httpx.Response(
            403,
            json={"error": {"errors": [{"reason": "quotaExceeded"}]}},
            request=request,
        )
    transport = external_policy.guarded_transport(
        "wikidata", "source_collection", httpx.MockTransport(handler)
    )
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(external_policy.FreeQuotaExceeded),
    ):
        client.get("https://www.wikidata.org/w/api.php")


def test_grounding_rejects_numbers_urls_and_wrong_language() -> None:
    sources = [
        {
            "id": "source",
            "url": "https://example.com/release",
            "evidence": "The rate is 5 percent.",
            "rights": "Public domain",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }
    ]
    draft = Draft(
        title="Unsupported claim",
        body="## Source\nThe rate is 99 percent. https://invented.example/page",
        summary="English text only with an invented financial figure",
        keywords=["rate"],
        source_ids=["source"],
    )
    result = inspect(draft, sources, "ko", datetime.now(UTC).date().isoformat())
    assert not result["rule_checks"]["no_unverified_numbers"]
    assert not result["rule_checks"]["no_fabricated_urls"]
    assert not result["rule_checks"]["language_script_present"]
    assert result["publish_ready"] is False


def test_collection_bounded_and_no_arbitrary_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(EngineFailure, match="collection_endpoint_not_approved"):
        collection.retrieve({"adapter": "fed_rss", "endpoint": "http://127.0.0.1:5432"}, [])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!DOCTYPE bad><rss/>")

    base = httpx.Client
    monkeypatch.setattr(
        collection, "external_client",
        lambda provider, operation, **kw: base(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(EngineFailure, match="unsafe_feed"):
        collection.retrieve({"adapter": "fed_rss", "endpoint": collection.ENDPOINTS["fed_rss"]}, [])


def test_collection_durable_retry_and_idempotency(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _, _ = lab

    @contextmanager
    def shared() -> Any:
        with conn.transaction():
            yield conn

    monkeypatch.setattr(collection, "connection", shared)
    conn.execute(
        "UPDATE job_runs SET created_at=created_at-interval '2 hours' WHERE task_kind='collection'"
    )
    source = conn.execute("SELECT * FROM collection_sources WHERE adapter='fed_rss'").fetchone()
    profile = conn.execute(
        "SELECT id FROM language_profiles WHERE language_code='en' AND target_country=''"
    ).fetchone()["id"]
    category = conn.execute(
        "SELECT category_id FROM collection_topics WHERE source_id=%s", (source["id"],)
    ).fetchone()["category_id"]
    key = uuid.uuid4().hex
    job = collection.request(source["id"], profile, key)
    assert collection.request(source["id"], profile, key)["id"] == job["id"]
    with pytest.raises(EngineFailure, match="collection_hourly_limit"):
        collection.request(source["id"], profile, uuid.uuid4().hex)

    def fail(*args: Any) -> Any:
        raise EngineFailure("collection_network_error", True)

    monkeypatch.setattr(collection, "retrieve", fail)
    assert collection.tick()
    assert (
        conn.execute("SELECT status FROM job_runs WHERE id=%s", (job["id"],)).fetchone()["status"]
        == "queued"
    )
    item = {
        "external_id": uuid.uuid4().hex,
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/example.htm",
        "title": "Test feed " + uuid.uuid4().hex,
        "evidence": "Synthetic collector test content only",
        "published_at": datetime.now(UTC),
        "category_id": category,
        "primary": True,
        "valid_until": datetime.now(UTC) + timedelta(days=1),
    }
    monkeypatch.setattr(collection, "retrieve", lambda *args: [item])
    conn.execute("UPDATE job_runs SET available_at=now() WHERE id=%s", (job["id"],))
    assert collection.tick()
    assert (
        conn.execute("SELECT status FROM job_runs WHERE id=%s", (job["id"],)).fetchone()["status"]
        == "succeeded"
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM collection_items WHERE external_id=%s",
            (item["external_id"],),
        ).fetchone()["n"]
        == 1
    )
    # Replaying the same run after interruption cannot duplicate the collected version.
    conn.execute("UPDATE job_runs SET status='queued',available_at=now() WHERE id=%s", (job["id"],))
    assert collection.tick()
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM collection_items WHERE external_id=%s",
            (item["external_id"],),
        ).fetchone()["n"]
        == 1
    )


def test_stream_cancellation_and_model_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from woori import local_inference as local

    monkeypatch.setattr(
        local,
        "runtime",
        lambda: {
            "pid": __import__("os").getpid(),
            "model": "test.gguf",
            "engine": "mock transport",
        },
    )
    base = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            text="data: " + json.dumps({"choices": [{"delta": {"content": "{"}}]}) + "\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: base(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(local, "cancelled", lambda _: True)
    monkeypatch.setattr(local, "auth_headers", lambda: {"Authorization": "Bearer synthetic-test"})
    context = {"language_code": "en", "sources": [{"id": "source", "evidence": "test"}]}
    with pytest.raises(EngineFailure, match="generation_cancelled"):
        LlamaCppProvider().generate(
            context, {"model": "test.gguf", "language_verified": True, "timeout_seconds": 5}
        )
    with pytest.raises(EngineFailure, match="local_model_mismatch"):
        LlamaCppProvider().generate(context, {"model": "other.gguf", "language_verified": True})


def test_article_parser_excludes_navigation() -> None:
    parser = collection.Paragraphs()
    parser.feed(
        '<p>Navigation content that must never enter evidence extraction.</p><div id="article"><p>Verified official article content with sufficient length.</p></div><p>Footer content that must never enter evidence extraction.</p>'
    )
    assert parser.parts == ["Verified official article content with sufficient length."]


def test_evaluation_cannot_silently_use_mock(lab: Any) -> None:
    from test_pipeline import topic

    _, api, headers = lab
    keyword, _ = topic(lab)
    response = api.post(
        "/admin/research/jobs",
        headers=headers,
        json={"keyword_id": keyword, "idempotency_key": uuid.uuid4().hex, "evaluation_only": True},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "evaluation_requires_real_local_provider"


def test_quality_revalidation_appends_without_changing_version(lab: Any) -> None:
    from test_pipeline import run_job, topic

    conn, api, headers = lab
    keyword, _ = topic(lab)
    job = run_job(lab, keyword)
    version = conn.execute(
        "SELECT v.* FROM generation_results g JOIN content_versions v ON v.id=g.content_version_id WHERE g.run_id=%s LIMIT 1",
        (job["id"],),
    ).fetchone()
    before = conn.execute(
        "SELECT count(*) AS n FROM seo_audits WHERE content_version_id=%s", (version["id"],)
    ).fetchone()["n"]
    response = api.post(f"/admin/research/versions/{version['id']}/validate", headers=headers)
    assert response.status_code == 200
    assert response.json()["publish_ready"] is False
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM seo_audits WHERE content_version_id=%s", (version["id"],)
        ).fetchone()["n"]
        == before + 1
    )
    assert (
        conn.execute("SELECT body FROM content_versions WHERE id=%s", (version["id"],)).fetchone()[
            "body"
        ]
        == version["body"]
    )


def test_phase3_legacy_idempotency_key_preserved(lab: Any) -> None:
    from test_pipeline import topic
    from woori import pipeline

    conn, _, _ = lab
    keyword, profiles = topic(lab)
    key = uuid.uuid4().hex
    job = pipeline.enqueue(uuid.UUID(keyword), key)
    legacy = hashlib.sha256(
        json.dumps([keyword, sorted(str(p) for p in profiles)]).encode()
    ).hexdigest()
    conn.execute(
        "UPDATE generation_jobs SET request_fingerprint=%s WHERE run_id=%s", (legacy, job["id"])
    )
    assert pipeline.enqueue(uuid.UUID(keyword), key)["id"] == job["id"]


def test_short_secret_uuid_collision_does_not_hide_plaintext() -> None:
    from woori.secret_scan import contains_secret

    public_id = "00000000-0000-4000-8000-0000abcd0000"
    assert not contains_secret(public_id, "abcd")
    assert contains_secret(public_id + " password=abcd", "abcd")
    assert contains_secret(public_id, public_id)
    assert contains_secret("password=abcd", "abcd")
