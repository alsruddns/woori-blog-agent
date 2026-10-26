import hashlib
import json
import subprocess
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from test_pipeline import lab as shared_lab

lab = shared_lab
from woori import collection, external_policy, local_inference
from woori.ai import Draft, EngineFailure
from woori.grounding import inspect, numbers, proper_names
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


def test_model_artifact_gate_is_narrowly_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    external_policy._authorize(
        "artifact_setup",
        "artifact_download",
        httpx.Request(
            "GET",
            "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf",
        ),
    )
    external_policy._authorize(
        "artifact_setup",
        "artifact_download",
        httpx.Request("GET", "https://us.aws.cdn.hf.co/xet-bridge-us/immutable-object-id"),
    )
    with pytest.raises(external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"):
        external_policy._authorize(
            "artifact_setup",
            "artifact_download",
            httpx.Request("GET", "https://us.aws.cdn.hf.co/other/path"),
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


def test_gpu_counter_is_scoped_to_inference_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_inference.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "37.5\n", ""),
    )
    assert local_inference.gpu_engine_percent(1234) == 37.5
    monkeypatch.setattr(
        local_inference.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    assert local_inference.gpu_engine_percent(1234) is None


def test_grounding_requires_source_markers_and_preserves_names() -> None:
    sources = [{
        "id": "acme-1",
        "url": "https://example.com/report",
        "evidence": "Acme Research published a report.",
        "rights": "Public domain test fixture",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }]
    clean = Draft(
        title="Acme Research report",
        body="## Overview\nAcme Research published a report [source:acme-1].",
        summary="Acme Research published a report.",
        keywords=["Acme Research"],
        source_ids=["acme-1"],
    )
    result = inspect(clean, sources, "en", datetime.now(UTC).date().isoformat())
    assert result["rule_checks"]["proper_names_preserved"]
    assert result["rule_checks"]["factual_paragraphs_cited"]
    assert result["rule_checks"]["citation_ids_valid"]
    assert result["source_url_network_existence"] == "not_rechecked_by_quality_gate"
    assert result["publish_ready"] is False

    bad = clean.model_copy(update={
        "title": "Unknown Startup report",
        "summary": "A startup published a report without supporting sources.",
        "body": "## Overview\nUnknown Startup published a report without a source marker.\n\n"
        "Unknown Startup published a report without a source marker.",
    })
    blocked = inspect(bad, sources, "en", datetime.now(UTC).date().isoformat())
    assert not blocked["rule_checks"]["proper_names_preserved"]
    assert not blocked["rule_checks"]["no_unsupported_proper_names"]
    assert not blocked["rule_checks"]["factual_paragraphs_cited"]
    assert not blocked["rule_checks"]["no_repeated_paragraphs"]


def test_extract_facts_keeps_source_identity() -> None:
    from woori.grounding import extract_facts

    facts = extract_facts([{"id": "source-1", "evidence": "First fact. Second fact!"}])
    assert [fact["text"] for fact in facts] == ["First fact.", "Second fact!"]
    assert all(fact["source_id"] == "source-1" for fact in facts)
    assert facts[0]["fact_id"] != facts[1]["fact_id"]
    assert facts == extract_facts([{"id": "source-1", "evidence": "First fact. Second fact!"}])


def test_section_claim_gate_checks_numbers_names_and_citations() -> None:
    from woori.grounding import extract_facts
    from woori.pipeline import section_response_valid

    source = {"id": "source-1", "evidence": "Federal Reserve Board issued a public notice."}
    facts = extract_facts([source])
    valid = Draft(
        title="Federal Reserve Board notice",
        body="Federal Reserve Board issued a public notice. [source:source-1]",
        summary="A sourced notice from the Federal Reserve Board.",
        keywords=["notice"],
        source_ids=["source-1"],
    )
    assert section_response_valid(valid, facts, {"source-1"}, "2026-10-26")["passed"]
    numbered_heading = valid.model_copy(update={"body": "## 1\n" + valid.body})
    assert section_response_valid(numbered_heading, facts, {"source-1"}, "2026-10-26")["passed"]
    unsupported = valid.model_copy(
        update={"body": "Federal Reserve Board issued a $99 million notice. [source:source-1]"}
    )
    failed = section_response_valid(unsupported, facts, {"source-1"}, "2026-10-26")
    assert not failed["passed"] and not failed["checks"]["numbers_from_evidence"]
    unknown_citation = valid.model_copy(update={"body": "Federal Reserve Board notice. [source:other]"})
    failed = section_response_valid(unknown_citation, facts, {"source-1"}, "2026-10-26")
    assert not failed["passed"] and not failed["checks"]["citations_allowed"]
    invented_name = valid.model_copy(
        update={
            "body": "Federal Reserve Board and European Central Bank issued a public notice. "
            "[source:source-1]"
        }
    )
    failed = section_response_valid(invented_name, facts, {"source-1"}, "2026-10-26")
    assert not failed["passed"] and not failed["checks"]["no_unsupported_proper_names"]
    assert "European Central Bank" in failed["unsupported_proper_names"]


def test_grounding_normalizes_dates_and_avoids_sentence_boundary_name_false_positives() -> None:
    assert numbers("October 16, 2026") == numbers("2026-10-16") == numbers("20261016")
    names = proper_names(
        "The Federal Reserve Board announced. Kansas. Cease and Desist Order. Terminated October."
    )
    assert "Federal Reserve Board" in names
    assert "Kansas Cease" not in names
    assert "Terminated October" not in names


def test_number_only_markdown_headings_are_not_factual_numbers() -> None:
    assert numbers("## 1\n## 2\n## 10") == set()
    assert numbers("## 1\nThe rate was 5 percent.") == {"5.0"}
    assert numbers("October 13, 2026") == numbers("2026년 10월 13일")
    assert numbers("2026-10-13") == numbers("2026年10月13日")


def test_repeated_source_markers_do_not_count_as_repeated_content() -> None:
    from woori.grounding import repeated_sentences

    text = "## Evidence\n> First verified statement [source:source-123456].\n\n"
    text += "> Second verified statement [source:source-123456].\n\n## Sources\n"
    text += "- Official source https://example.com/long-reference\n"
    assert repeated_sentences(text) == []


def test_historical_english_headlines_do_not_create_generic_proper_names() -> None:
    names = proper_names(
        "Federal Reserve Board Announces Termination of Enforcement Actions "
        "with Gardner Bancshares, Inc."
    )
    assert "Federal Reserve Board" in names
    assert "Gardner Bancshares" in names
    assert "Federal Reserve Board Announces" not in names
    assert "Enforcement Actions" not in names
    assert "Federal Reserve Board's" in proper_names("Federal Reserve Board's policy")


def test_cited_text_prefixed_as_markdown_heading_is_still_validated() -> None:
    source = {
        "id": "source-1", "url": "https://example.com/source",
        "evidence": "Federal Reserve Board issued a public notice.",
        "rights": "Public domain",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    draft = Draft(
        title="Federal Reserve Board notice",
        body="## European Central Bank announced a 9 percent rate change. [source:source-1]",
        summary="A notice from the Federal Reserve Board.",
        keywords=["Federal Reserve Board"], source_ids=["source-1"],
    )
    result = inspect(draft, [source], "en", "2026-10-26")
    assert not result["rule_checks"]["no_unsupported_proper_names"]
    assert not result["rule_checks"]["no_unverified_numbers"]
    assert "European Central Bank" in result["unsupported_proper_names"]


def test_evidence_template_preserves_source_text_and_holds_unlocalized_language() -> None:
    from woori.evidence_template import build_evidence_template

    source = {
        "id": "source-1",
        "source_name": "Federal Reserve Board",
        "url": "https://example.com/source",
        "evidence": "Federal Reserve Board terminated the action on October 13, 2026.",
        "published_at": "2026-10-13",
        "rights": "Public domain",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    draft, metrics = build_evidence_template([source], "en", "Federal Reserve", "2026-10-26")
    assert source["evidence"] in draft.body
    assert "[source:source-1]" in draft.body
    assert metrics["ai_calls"] == 0
    checked = inspect(draft, [source], "en", "2026-10-26")
    assert checked["rule_pass"]

    ko_draft, _ = build_evidence_template([source], "ko", "Federal Reserve", "2026-10-26")
    ko_checked = inspect(ko_draft, [source], "ko", "2026-10-26")
    assert not ko_checked["rule_checks"]["language_metadata_matches"]
    with pytest.raises(ValueError, match="template_language_not_evaluated"):
        build_evidence_template([source], "ja", "Federal Reserve", "2026-10-26")


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
