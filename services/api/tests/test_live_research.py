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
from test_pipeline import topic as make_topic

lab = shared_lab
from woori import collection, external_policy, local_inference, pipeline
from woori.ai import Draft, EngineFailure
from woori.grounding import inspect, numbers, proper_names
from woori.local_inference import LlamaCppProvider
from woori.localization import fact_ledger, localize_fact

_ORIGINAL_EVALUATION_DB_ISOLATION = pipeline.evaluation_database_isolated


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
            "federal_reserve",
            "source_collection",
            httpx.Request("GET", "https://www.federalreserve.gov/feeds/press_all.xml"),
        )


def test_external_policy_blocks_unlisted_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    with pytest.raises(
        external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"
    ):
        external_policy._authorize(
            "google_blogger_read",
            "blogger_read",
            httpx.Request("GET", "https://example.com/blogger/v3/blogs/1"),
        )
    with pytest.raises(
        external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"
    ):
        external_policy._authorize(
            "artifact_setup",
            "artifact_download",
            httpx.Request("GET", "https://api.github.com/repos/other/project/releases"),
        )


def test_sec_edgar_is_restricted_to_free_submissions_and_companyconcept_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    external_policy._authorize(
        "sec_edgar",
        "source_collection",
        httpx.Request("GET", "https://data.sec.gov/submissions/CIK0000320193.json"),
    )
    external_policy._authorize(
        "sec_edgar",
        "source_collection",
        httpx.Request(
            "GET",
            "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/NetIncomeLoss.json",
        ),
    )
    for url in (
        "https://data.sec.gov/api/private/anything",
        "https://www.sec.gov/Archives/edgar/data/1/a.htm",
    ):
        with pytest.raises(
            external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"
        ):
            external_policy._authorize("sec_edgar", "source_collection", httpx.Request("GET", url))


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
        httpx.Request(
            "GET",
            "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/ae44f08e1392f39c0e474af10c3ff8355c8b6688/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        ),
    )
    external_policy._authorize(
        "artifact_setup",
        "artifact_download",
        httpx.Request(
            "GET",
            "https://huggingface.co/api/models/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/revision/ae44f08e1392f39c0e474af10c3ff8355c8b6688?blobs=true",
        ),
    )
    external_policy._authorize(
        "artifact_setup",
        "artifact_download",
        httpx.Request("GET", "https://us.aws.cdn.hf.co/xet-bridge-us/immutable-object-id"),
    )
    with pytest.raises(
        external_policy.ExternalCallBlocked, match="destination_or_method_not_allowlisted"
    ):
        external_policy._authorize(
            "artifact_setup",
            "artifact_download",
            httpx.Request("GET", "https://us.aws.cdn.hf.co/other/path"),
        )


def test_evaluation_dashboard_is_empty_when_read_only_connection_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from woori import config, research_routes

    monkeypatch.setattr(config, "settings", lambda: SimpleNamespace(evaluation_database_url=""))
    assert research_routes._evaluation_results_snapshot() == {
        "configured": False, "runs": [], "stages": []
    }


def test_worker_single_shot_mode_requires_evaluation_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from woori import worker

    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    with pytest.raises(SystemExit, match="reserved for the isolated evaluation worker"):
        worker.main()


def test_localized_translation_records_measured_usage_and_resource_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_request: dict[str, Any] = {}

    class FakeProcess:
        pid = 123

        def cpu_percent(self, interval: float | None = None) -> float:
            return 5.0

        def memory_info(self) -> Any:
            return type("Memory", (), {"rss": 1024 * 1024 * 128})()

    class FakeResponse:
        content = b'{"choices":[{"message":{"content":"{\\"localized_text\\":\\"Hello\\"}"}}],"usage":{"prompt_tokens":12,"completion_tokens":3}}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": '{"localized_text":"Hello"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def close(self) -> None:
            return None

        def post(self, *_args: Any, **kwargs: Any) -> FakeResponse:
            captured_request.update(kwargs.get("json", {}))
            return FakeResponse()

    monkeypatch.setattr(local_inference, "runtime", lambda: {"pid": 123, "model": "local", "backend": "cpu", "gpu_layers": 0})
    monkeypatch.setattr(local_inference, "auth_headers", dict)
    monkeypatch.setattr(local_inference.psutil, "Process", lambda _pid: FakeProcess())
    monkeypatch.setattr(local_inference.httpx, "Client", FakeClient)
    metrics: list[dict[str, Any]] = []
    result = local_inference.localized_translation(
        "Hello", "en", [], [], "local", 5, mode="faithful_paraphrase", metrics_sink=metrics
    )
    assert result == "Hello"
    system_prompt = captured_request["messages"][0]["content"]
    assert "natural target-language editorial prose" in system_prompt
    assert "Do not copy a complete source sentence" in system_prompt
    assert metrics[0]["prompt_tokens"] == 12
    assert metrics[0]["completion_tokens"] == 3
    assert metrics[0]["succeeded"] is True
    assert metrics[0]["rss_peak_mib"] >= 128


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
def test_external_policy_quota_is_a_hard_stop(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
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
    sources = [
        {
            "id": "acme-1",
            "url": "https://example.com/report",
            "evidence": "Acme Research published a report.",
            "rights": "Public domain test fixture",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }
    ]
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

    bad = clean.model_copy(
        update={
            "title": "Unknown Startup report",
            "summary": "A startup published a report without supporting sources.",
            "body": "## Overview\nUnknown Startup published a report without a source marker.\n\n"
            "Unknown Startup published a report without a source marker.",
        }
    )
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
    unknown_citation = valid.model_copy(
        update={"body": "Federal Reserve Board notice. [source:other]"}
    )
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


def test_proper_names_allow_adjacent_korean_particles_without_relaxing_name_matching() -> None:
    names = proper_names(
        "Federal Reserve Board? ??? ???. "
        "Federal Open Market Committee? ?? ??? ???."
    )
    assert "Federal Reserve Board" in names
    assert "Federal Open Market Committee" in names
    assert "European Central Bank" not in names


def test_number_only_markdown_headings_are_not_factual_numbers() -> None:
    assert numbers("## 1\n## 2\n## 10") == set()


def test_grouped_financial_amounts_normalize_to_the_same_numeric_fact() -> None:
    assert numbers("Revenue was 109417000000 USD") == numbers(
        "Revenue was 109,417,000,000 USD"
    )


def test_taiwan_budget_currency_scales_normalize_without_hiding_amount_changes() -> None:
    assert numbers("6,076億元") == numbers("NT$607.6 billion")
    assert numbers("107億元") == numbers("NT$10.7 billion")
    assert numbers("2,000元") == numbers("NT$2,000")
    assert numbers("107億元") != numbers("NT$10.8 billion")


def test_taiwan_fiscal_years_match_gregorian_years_without_weakening_other_numbers() -> None:
    assert numbers("116年度") == numbers("fiscal 2027") == numbers("2027년도")
    assert numbers("115年度") == numbers("fiscal 2026")
    assert numbers("fiscal 2027") != numbers("fiscal 2028")


def test_inherited_year_date_lists_match_localized_dates() -> None:
    source = "Minutes of the Board's discount rate meetings on August 17, September 9, and September 16, 2026."
    localized = "2026\ub144 8\uc6d4 17\uc77c, 9\uc6d4 9\uc77c, 9\uc6d4 16\uc77c"
    assert numbers(source) == numbers(localized)
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
    assert "Q Filed" not in proper_names("Apple Inc. Form 10-Q Filed on 2026-07-31")
    assert "Board's Discount Rate Meetings" not in proper_names(
        "Minutes of the Board's Discount Rate Meetings"
    )


def test_cited_text_prefixed_as_markdown_heading_is_still_validated() -> None:
    source = {
        "id": "source-1",
        "url": "https://example.com/source",
        "evidence": "Federal Reserve Board issued a public notice.",
        "rights": "Public domain",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    draft = Draft(
        title="Federal Reserve Board notice",
        body="## European Central Bank announced a 9 percent rate change. [source:source-1]",
        summary="A notice from the Federal Reserve Board.",
        keywords=["Federal Reserve Board"],
        source_ids=["source-1"],
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


def test_fact_ledger_and_localization_separate_source_language_and_expression() -> None:
    from woori.localization import fact_ledger, localize_fact

    source = {
        "id": "fed-source",
        "source_language": "en",
        "evidence": "Federal Reserve Board ended the action on October 13, 2026.",
    }
    fact = fact_ledger(source)[0]
    assert fact["source_excerpt"] == source["evidence"]
    assert fact["citation_ids"] == ["fed-source"]
    assert fact["date_values"] == ["DATE:2026-10-13"]
    assert fact["verification_status"] == "source_span_verified"

    # Original English text cannot be mistaken for a Korean translation.
    held = localize_fact(fact, "ko")
    assert held["status"] == "held_translation_unavailable"
    assert not held["checks"]["language_matches"]
    assert held["publish_ready"] is False

    glossary = [
        {
            "source_term": "Federal Reserve Board",
            "localized_term": "연방준비제도",
            "source_language": "en",
            "target_language": "ko",
            "approved": True,
            "official_translation": True,
            "translation_source": "https://example.org/official-glossary",
        }
    ]
    localized = localize_fact(
        fact, "ko", lambda *_: "Federal Reserve Board는 2026년 10월 13일 조치를 종료했다.", glossary
    )
    assert localized["checks"]["language_matches"]
    assert localized["checks"]["numbers_preserved"]
    assert localized["checks"]["entities_preserved"]
    assert "연방준비제도" in localized["text"]
    assert localized["source_ids"] == ["fed-source"]
    assert localized["human_review_required"] and not localized["publish_ready"]


def test_long_official_topic_label_uses_bounded_search_intent_phrase() -> None:
    from woori.article_quality import search_intent_phrase

    label = (
        "Minutes of the Board's discount rate meetings on August 17, September 9, "
        "and September 16, 2026"
    )
    assert search_intent_phrase(label) == "Minutes of the Board's discount rate meetings"
    assert search_intent_phrase("x" * 81) == ""


def test_localization_holds_exact_long_source_sentence_and_accepts_bounded_restatement() -> None:
    from woori.localization import fact_ledger, localize_fact

    source = {
        "id": "fed-source",
        "source_language": "en",
        "evidence": (
            "The Board's process for setting the discount rate is distinct from the process "
            "the Federal Open Market Committee follows in setting the target range for the "
            "federal funds rate."
        ),
    }
    fact = fact_ledger(source)[0]
    copied = localize_fact(
        fact, "en", lambda excerpt, *_: excerpt, force_local=True,
    )
    assert copied["checks"]["no_mass_direct_quote"] is False
    assert copied["longest_source_overlap_words"] == 30
    assert copied["status"] == "quality_held"
    assert copied["publish_ready"] is False

    restated = localize_fact(
        fact,
        "en",
        lambda *_: (
            "Federal Reserve Board distinguishes its discount-rate process from how the "
            "Federal Open Market Committee sets the federal funds target range."
        ),
        force_local=True,
    )
    assert restated["checks"]["no_mass_direct_quote"] is True
    assert restated["longest_source_overlap_words"] < 25
    assert restated["human_review_required"] is True
    assert restated["publish_ready"] is False


def test_localization_blocks_number_date_and_unapproved_entity_drift() -> None:
    from woori.localization import fact_ledger, localize_fact


    fact = fact_ledger(
        {
            "id": "fed-source",
            "source_language": "en",
            "evidence": "Federal Reserve Board ended the action on October 13, 2026.",
        }
    )[0]
    changed = localize_fact(
        fact, "ko", lambda *_: "연방준비제도는 2026년 10월 14일 조치를 종료했고 9%를 기록했다."
    )
    assert not changed["checks"]["numbers_preserved"]
    assert changed["status"] == "quality_held"
    assert not changed["publish_ready"]

    # No AI/translation adapter is a safe refusal, never a source-language success.
    refused = localize_fact(
        fact,
        "fr",
        glossary=[
            {
                "source_term": "Federal Reserve Board",
                "localized_term": "Conseil de la Réserve fédérale",
                "target_language": "fr",
                "approved": False,
                "official_translation": False,
            }
        ],
    )
    assert refused["status"] == "held_translation_unavailable"

    unapproved_term = localize_fact(
        fact,
        "fr",
        lambda *_: "Le Conseil de la Réserve fédérale a publié un rapport.",
        [
            {
                "source_term": "Federal Reserve Board",
                "localized_term": "Conseil de la Réserve fédérale",
                "target_language": "fr",
                "approved": False,
                "official_translation": False,
            }
        ],
    )
    assert unapproved_term["checks"]["no_unapproved_translation_asserted"] is False
    assert unapproved_term["status"] == "quality_held"

    preserved_name = localize_fact(
        fact, "ko", lambda *_: "Federal Reserve Board은 화요일 공식 공지를 발표했습니다."
    )
    assert preserved_name["checks"]["entities_preserved"]
    assert preserved_name["checks"]["no_unverified_entity_added"]


def test_local_translation_protects_entity_spans_and_fails_if_marker_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import local_inference as inference

    monkeypatch.setattr(inference, "runtime", lambda: {"model": "local-test-model"})
    monkeypatch.setattr(inference, "auth_headers", dict)
    base_client = httpx.Client
    observed: list[str] = []

    def execute(response_text: str) -> str:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            observed.append(payload["messages"][1]["content"])
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"localized_text": response_text}, ensure_ascii=False
                                )
                            }
                        }
                    ]
                },
            )

        monkeypatch.setattr(
            inference.httpx,
            "Client",
            lambda *args, **kwargs: base_client(transport=httpx.MockTransport(handler), **kwargs),
        )
        return inference.localized_translation(
            "The Federal Reserve Board issued a notice.",
            "ko",
            [],
            ["Federal Reserve Board"],
            "local-test-model",
            10,
        )

    restored = execute("[[LOCKED_ENTITY_0001]]가 공지를 발표했습니다.")
    assert restored == "Federal Reserve Board가 공지를 발표했습니다."
    assert "[[LOCKED_ENTITY_0001]]" in observed[0]
    with pytest.raises(EngineFailure, match="localization_entity_placeholder_error"):
        execute("기관이 공지를 발표했습니다.")


def test_local_translation_locks_dates_and_numbers_and_rejects_missing_or_duplicate_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import local_inference as inference

    monkeypatch.setattr(inference, "runtime", lambda: {"model": "local-test-model"})
    monkeypatch.setattr(inference, "auth_headers", dict)
    base_client = httpx.Client
    observed: list[dict[str, Any]] = []

    def execute(response_text: str) -> str:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            observed.append(json.loads(payload["messages"][1]["content"]))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"localized_text": response_text})}}
                    ]
                },
            )

        monkeypatch.setattr(
            inference.httpx,
            "Client",
            lambda *args, **kwargs: base_client(transport=httpx.MockTransport(handler), **kwargs),
        )
        return inference.localized_translation(
            "On June 17, 2026, the board reported 1,234 items and a 3.5 percent change.",
            "ko",
            [],
            [],
            "local-test-model",
            10,
        )

    # The exact source date remains immutable. Localized display conversion is
    # a separate deterministic presentation concern and is not model-authored.
    expected = "June 17, 2026에 위원회는 1,234개 항목과 3.5 퍼센트 변화를 보고했습니다."
    response = (
        "[[LOCKED_DATE_0001]]에 위원회는 [[LOCKED_NUMBER_0002]]개 항목과 "
        "[[LOCKED_NUMBER_0003]] 퍼센트 변화를 보고했습니다."
    )
    assert execute(response) == expected
    payload = observed[-1]
    assert "[[LOCKED_DATE_0001]]" in payload["source_excerpt"]
    assert "[[LOCKED_NUMBER_0002]]" in payload["source_excerpt"]
    assert "[[LOCKED_NUMBER_0003]]" in payload["source_excerpt"]
    assert len(payload["protected_values"]) == 3
    assert "[[LOCKED_" not in expected

    with pytest.raises(EngineFailure, match="localization_protected_value_placeholder_error"):
        execute("[[LOCKED_DATE_0001]]에 위원회는 [[LOCKED_NUMBER_0002]]개 항목을 보고했습니다.")

    with pytest.raises(EngineFailure, match="localization_protected_value_placeholder_error"):
        execute(
            "[[LOCKED_DATE_0001]]에 위원회는 [[LOCKED_NUMBER_0002]]개와 "
            "[[LOCKED_NUMBER_0002]]개 항목을 보고했습니다."
        )

    with pytest.raises(EngineFailure, match="localization_protected_value_placeholder_error"):
        execute(
            "[[LOCKED_DATE_0001]]에 위원회는 [[LOCKED_NUMBER_0002]]개 항목과 "
            "[[LOCKED_NUMBER_0003]] 퍼센트 변화를 보고했습니다. [[LOCKED_NUMBER_99999]]"
        )


def test_numeric_and_date_formatting_normalization_does_not_hide_value_changes() -> None:
    from woori.grounding import numbers

    assert numbers("The reported amount was 1,234.") == numbers("보고 금액은 1234입니다.")
    assert numbers("The date was October 27, 2026.") == numbers("기준일은 2026년 10월 27일입니다.")
    assert numbers("The filing date was 2026-07-31.") == numbers("공시는 2026-07-31에 제출됐습니다.")
    assert numbers("The reported amount was 1,234.") != numbers("보고 금액은 1,235입니다.")
    assert numbers("The date was October 27, 2026.") != numbers("기준일은 2026년 10월 28일입니다.")
    assert numbers("The filing date was 2026-07-31.") != numbers("공시는 2026-07-30에 제출됐습니다.")


def test_reviewed_source_facts_and_localization_are_durable_and_fail_closed(lab: Any) -> None:
    from test_pipeline import topic

    conn, api, headers = lab
    keyword_id, _ = topic(lab)
    source = conn.execute(
        "SELECT id FROM research_sources WHERE keyword_id=%s ORDER BY revision DESC LIMIT 1",
        (keyword_id,),
    ).fetchone()
    language_review = api.post(
        f"/admin/research/sources/{source['id']}/reviews",
        headers=headers,
        json={
            "approved": True,
            "reason": "Synthetic fixture is authored in English for this test.",
            "reviewer": "Test reviewer",
            "source_language": "en",
        },
    )
    assert language_review.status_code == 201, language_review.text
    extracted = api.post(f"/admin/research/sources/{source['id']}/facts", headers=headers)
    assert extracted.status_code == 201, extracted.text
    fact = extracted.json()["facts"][0]
    assert fact["source_language"] == "en"
    assert fact["citation_ids"]
    assert fact["verification_status"] == "source_span_verified"

    # Same-language rendering is deterministic; Korean without local AI remains held.
    english = api.post(
        "/admin/research/localizations",
        headers=headers,
        json={"fact_id": fact["id"], "target_language": "en"},
    )
    assert english.status_code == 201, english.text
    assert english.json()["machine_passed"] is True
    assert english.json()["publish_ready"] is False
    result = api.post(
        "/admin/research/localizations",
        headers=headers,
        json={"fact_id": fact["id"], "target_language": "ko"},
    )
    assert result.status_code == 201, result.text
    assert result.json()["machine_passed"] is False
    assert result.json()["publish_ready"] is False
    saved = result.json()["output_snapshot"]
    assert saved["status"] == "held_translation_language_unverified"

    state = api.get("/admin/research/state", headers=headers)
    assert state.status_code == 200
    assert any(row["id"] == fact["id"] for row in state.json()["evidence_facts"])
    assert any(row["id"] == result.json()["id"] for row in state.json()["localizations"])


def test_localized_template_composes_only_passed_fact_spans() -> None:
    from woori.evidence_template import build_localized_evidence_template

    source = {
        "id": "source-1",
        "url": "https://www.federalreserve.gov/test",
        "source_name": "Federal Reserve Board",
        "evidence": "Federal Reserve Board issued a public informational notice on Tuesday regarding the latest enforcement action.",
        "rights": "Public domain",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    fact = {
        "text": "Federal Reserve Board, 화요일 최신 집행 조치에 관한 공식 정보 안내문을 발표했습니다.",
        "target_language": "ko",
        "status": "machine_passed",
        "source_ids": ["source-1"],
        "ai_calls": 0,
    }
    draft, metrics = build_localized_evidence_template(
        [source],
        [fact],
        "ko",
        "연방준비제도 공식 안내",
        "공식 안내의 핵심 내용을 정리했습니다.",
        ["공식 안내"],
    )
    assert "[source:source-1]" in draft.body
    assert metrics["human_review_required"] and not metrics["publish_ready"]
    with pytest.raises(ValueError, match="localization_quality_held"):
        build_localized_evidence_template(
            [source],
            [{**fact, "status": "held_translation_unavailable"}],
            "ko",
            "연방준비제도 공식 안내",
            "공식 안내의 핵심 내용을 정리했습니다.",
            ["공식 안내"],
        )


def test_collection_bounded_and_no_arbitrary_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(EngineFailure, match="collection_endpoint_not_approved"):
        collection.retrieve({"adapter": "fed_rss", "endpoint": "http://127.0.0.1:5432"}, [])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!DOCTYPE bad><rss/>")

    base = httpx.Client
    monkeypatch.setattr(
        collection,
        "external_client",
        lambda provider, operation, **kw: base(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(EngineFailure, match="unsafe_feed"):
        collection.retrieve({"adapter": "fed_rss", "endpoint": collection.ENDPOINTS["fed_rss"]}, [])


def test_sec_edgar_collector_is_bounded_and_records_filing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC

    monkeypatch.setenv("SEC_USER_AGENT_CONTACT", "research@example.test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(".json") and "/submissions/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "name": "Example Corporation",
                    "filings": {
                        "recent": {
                            "form": ["10-Q"],
                            "accessionNumber": ["0000123456-26-000007"],
                            "filingDate": ["2026-08-01"],
                            "reportDate": ["2026-06-30"],
                            "primaryDocument": ["quarterly.htm"],
                        }
                    },
                },
                request=request,
            )
        value = 1234567 if "RevenueFrom" in request.url.path else 765432
        return httpx.Response(
            200,
            json={
                "units": {
                    "USD": [
                        {
                            "accn": "0000123456-26-000007",
                            "end": "2026-06-30",
                            "start": "2026-04-01",
                            "val": value,
                        }
                    ]
                }
            },
            request=request,
        )

    base = httpx.Client
    monkeypatch.setattr(
        collection,
        "external_client",
        lambda provider, operation, **kw: base(transport=httpx.MockTransport(handler), **kw),
    )
    item = collection.retrieve(
        {"adapter": "sec_edgar", "endpoint": collection.ENDPOINTS["sec_edgar"]},
        [{"query": "0000123456", "category_id": "stocks-category"}],
    )[0]
    assert len(requests) == 3
    assert all(
        "WooriBlogAgent/0.3.8 (research@example.test)" == r.headers["user-agent"] for r in requests
    )
    assert item["source_language"] == "en" and item["retrieved_at"].tzinfo == UTC
    assert item["primary"] and item["category_id"] == "stocks-category"
    assert "10-Q" in item["evidence"] and "revenue: 1234567 USD" in item["evidence"]
    assert "net income: 765432 USD" in item["evidence"]
    assert item["url"].startswith("https://www.sec.gov/Archives/edgar/data/123456/")


def test_sec_edgar_requires_declared_contact_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEC_USER_AGENT_CONTACT", raising=False)
    called = False

    def no_network(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("network must not be attempted without SEC contact")

    monkeypatch.setattr(collection, "external_client", no_network)
    with pytest.raises(EngineFailure, match="sec_user_agent_contact_required"):
        collection.retrieve(
            {"adapter": "sec_edgar", "endpoint": collection.ENDPOINTS["sec_edgar"]}, []
        )
    assert not called


def test_complete_article_quality_separates_machine_checks_from_editorial_approval() -> None:
    from woori.article_quality import evaluate

    source = {
        "id": "source-1",
        "url": "https://www.federalreserve.gov/test.htm",
        "source_name": "Federal Reserve Board",
        "evidence": "The Federal Reserve Board issued a notice about its published review process and described how readers can find the official minutes.",
        "rights": "Official public-domain information; cite the Board.",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    draft = Draft(
        title="Federal Reserve Board minutes explained",
        body=(
            "## What the notice says\n\nThe Federal Reserve Board issued a notice about its published review process. [source:source-1]\n\n"
            "## How readers can use the filing\n\nReaders can consult the cited material to understand what the notice identifies. [source:source-1]\n\n"
            "## Limits of this summary\n\nThis summary describes the supplied notice and does not provide an investment recommendation. [source:source-1]"
        ),
        summary="A sourced guide to the Federal Reserve Board notice.",
        keywords=["Federal Reserve Board notice"],
        source_ids=["source-1"],
    )
    result = evaluate(draft, [source], "en", datetime.now(UTC).date().isoformat(), 3)
    assert result["machine_passed"]
    assert result["human_review_required"] and not result["publish_ready"]

    source["evidence"] = (
        "Federal Reserve Board published a notice and explained the official minutes. "
        + "Readers can find the official record for additional information about the review process. "
        * 2
    )
    quote_draft = draft.model_copy(
        update={
            "body": "## Source\n\n"
            + source["evidence"]
            + " [source:source-1]\n\n## Notes\n\nA guide describes the official record for readers. [source:source-1]\n\n## Limits\n\nNo advice is offered here. [source:source-1]"
        }
    )
    quote_result = evaluate(quote_draft, [source], "en", datetime.now(UTC).date().isoformat(), 3)
    assert not quote_result["checks"]["no_mass_direct_quote"]


def test_complete_article_structure_handles_cjk_scripts() -> None:
    from woori.article_quality import evaluate

    source = {
        "id": "source-1",
        "url": "https://www.federalreserve.gov/test.htm",
        "source_name": "Federal Reserve Board",
        "evidence": "The Federal Reserve Board issued an official notice for readers.",
        "rights": "Official source; cite the Board.",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    draft = Draft(
        title="Federal Reserve Board 공식 안내 해설",
        body=(
            "## 공식 안내의 내용\n\nFederal Reserve Board는 공식 안내를 발표했습니다. [source:source-1]\n\n"
            "## 자료를 읽는 방법\n\n독자는 인용된 자료에서 발표된 안내의 범위를 확인할 수 있습니다. [source:source-1]\n\n"
            "## 이 요약의 한계\n\n이 글은 제공된 안내만 요약하며 투자 권고를 하지 않습니다. [source:source-1]"
        ),
        summary="Federal Reserve Board의 공식 안내를 한국어로 정리합니다.",
        keywords=["Federal Reserve Board", "공식 안내"],
        source_ids=["source-1"],
    )
    result = evaluate(draft, [source], "ko", datetime.now(UTC).date().isoformat(), 3)
    assert result["machine_passed"]
    assert result["paragraph_count"] >= 3
    assert result["human_review_required"] and not result["publish_ready"]


def test_article_gate_allows_date_search_terms_but_holds_internal_ids() -> None:
    from woori.article_quality import evaluate

    source = {
        "id": "source-1",
        "url": "https://www.federalreserve.gov/test.htm",
        "source_name": "Federal Reserve Board",
        "evidence": "The Federal Reserve Board published an informational notice for readers.",
        "rights": "Official source; cite the Board.",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    body = (
        "## Notice\n\nThe Federal Reserve Board published an informational notice. [source:source-1]\n\n"
        "## Reading it\n\nReaders can consult the supplied notice for the information stated there. [source:source-1]\n\n"
        "## Scope\n\nThis is part of a public record and no other claims are made here. [source:source-1]"
    )
    draft = Draft(
        title="Federal Reserve Board notice explained",
        body=body,
        summary="A sourced guide to the Federal Reserve Board notice.",
        keywords=["Federal Reserve Board notice 2026-10-26"],
        source_ids=["source-1"],
    )
    result = evaluate(draft, [source], "en", "2026-10-26", 3)
    assert not result["checks"]["legal_access_claims_grounded_in_supplied_source"]
    assert result["checks"]["keywords_are_search_terms_not_internal_ids"]
    assert not result["machine_passed"]

    internal = draft.model_copy(update={"keywords": ["source:873093a8-085e-42b5-8bb2-657f62f8df94"]})
    internal_result = evaluate(internal, [source], "en", "2026-10-26", 3)
    assert not internal_result["checks"]["keywords_are_search_terms_not_internal_ids"]


def test_english_name_after_form_hyphen_is_not_a_spurious_name() -> None:
    from woori.grounding import proper_names

    assert proper_names("10-Q Apple Inc. filed 2026-07-31") == {"Apple Inc"}


def test_supported_currency_code_does_not_trigger_unsupported_proper_name() -> None:
    from woori.grounding import inspect

    source = {"id":"source-1","url":"https://www.sec.gov/example",
        "evidence":"Apple Inc. reported revenue of 109417000000 USD for the period.",
        "rights":"Official SEC filing."}
    draft = Draft(title="Apple Inc. revenue report",
        body="## Report\n\nApple Inc. reported 109417000000 United States Dollar. [source:source-1]\n\n"
             "## Scope\n\nThis summary covers the reported period only. [source:source-1]",
        summary="Apple Inc. reported revenue in USD.", keywords=["Apple Inc. revenue"], source_ids=["source-1"])
    checked = inspect(draft, [source], "en", datetime.now(UTC).date().isoformat())
    assert "United States Dollar" not in checked["unsupported_proper_names"]

    unsupported = dict(source, evidence="Apple Inc. reported revenue of 109417000000 for the period.")
    held = inspect(draft, [unsupported], "en", datetime.now(UTC).date().isoformat())
    assert "United States Dollar" in held["unsupported_proper_names"]


def test_korean_language_fields_allow_official_english_name_with_korean_text() -> None:
    from woori.grounding import inspect

    draft = Draft(
        title="Apple Inc. 공시 핵심 내용",
        body="## 공시 요약\n\nApple Inc.가 공시한 핵심 내용을 공식 자료와 함께 설명합니다. [source:source-1]\n\n"
             "## 기준일\n\n제출일과 보고 기간을 구분해 확인할 수 있습니다. [source:source-1]",
        summary="Apple Inc. 공시의 핵심 사실을 한국어로 정리합니다.",
        keywords=["Apple Inc. 공시 요약"],
        source_ids=["source-1"],
    )
    source = {"id":"source-1","url":"https://www.sec.gov/example","evidence":"Apple Inc. filed a report for readers.","rights":"Official SEC filing."}
    result = inspect(draft, [source], "ko", datetime.now(UTC).date().isoformat())
    assert result["rule_checks"]["language_metadata_matches"]


def test_complete_article_quality_blocks_internal_uuid_and_obvious_script_mixing() -> None:
    from woori.article_quality import evaluate

    source = {
        "id": "source-1",
        "url": "https://example.test/report",
        "source_name": "Federal Reserve Board",
        "evidence": "Federal Reserve Board published an official notice for readers.",
        "rights": "Official source, cite it.",
        "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    cyrillic = "\u0424\u0435\u0434\u0435\u0440\u0430\u043b\u044c\u043d\u044b\u0439 \u0441\u043e\u0432\u0435\u0442"
    draft = Draft(
        title="Federal Reserve Board notice",
        body=("## Notice\n\nFederal Reserve Board published an official notice for readers. "
              f"{cyrillic} published a notice. [source:source-1]"),
        summary="Federal Reserve Board notice summary.",
        keywords=["Federal Reserve Board"],
        source_ids=["source-1"],
    )
    result = evaluate(draft, [source], "en", datetime.now(UTC).date().isoformat(), 1)
    assert not result["checks"]["no_forbidden_foreign_script_mixing"]

    internal = draft.model_copy(update={
        "body": "## Notice\n\nFederal Reserve Board published an official notice for readers. "
        "[source:source-1] 123e4567-e89b-12d3-a456-426614174000",
    })
    internal_result = evaluate(internal, [source], "en", datetime.now(UTC).date().isoformat(), 1)
    assert not internal_result["checks"]["no_internal_ids_in_user_text"]


def test_structured_output_retry_is_limited_to_one_seeded_retry() -> None:
    from woori.inference_failures import generate_with_bounded_json_retry

    valid = Draft(
        title="Federal Reserve Board notice",
        body="## Notice\n\nA short notice.",
        summary="A short sourced notice.",
        keywords=["notice"],
        source_ids=["source-1"],
    )

    class Provider:
        def __init__(self) -> None:
            self.seeds: list[int] = []

        def generate(self, context: dict[str, Any], policy: dict[str, Any]) -> Draft:
            self.seeds.append(policy["seed"])
            if len(self.seeds) == 1:
                raise EngineFailure(
                    "local_model_output_schema_invalid",
                    failure_artifact={"raw_response": "{broken"},
                )
            return valid

    provider = Provider()
    archived: list[str] = []
    result, attempts = generate_with_bounded_json_retry(
        provider, {}, {"seed": 35}, archive=lambda exc: archived.append(exc.category)
    )
    assert result == valid and attempts == 2
    assert provider.seeds == [35, 36]
    assert archived == ["local_model_output_schema_invalid"]


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
    system_prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={})
        system_prompts.append(json.loads(request.content)["messages"][0]["content"])
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
    assert "reader-centered reported explainer or expert column" in system_prompts[0]
    assert "Avoid repeated caveats and internal workflow language" in system_prompts[0]
    assert "Never invent expert opinion, interviews, statistics" in system_prompts[0]
    with pytest.raises(EngineFailure, match="local_model_mismatch"):
        LlamaCppProvider().generate(context, {"model": "other.gguf", "language_verified": True})


def test_inference_resource_monitor_cancels_and_records_cpu_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from woori.local_inference import InferenceResourceMonitor

    class FakeProcess:
        def cpu_percent(self, interval: float | None = None) -> float:
            return 240.0

        def memory_info(self) -> Any:
            return SimpleNamespace(rss=128 * 1024**2)

    monkeypatch.setattr("woori.local_inference.psutil.cpu_count", lambda: 12)
    readings = iter([14.0, 79.5, 80.0])

    def read_system_cpu(*, interval: float | None = None) -> float:
        try:
            return next(readings)
        except StopIteration:
            return 80.0

    monitor = InferenceResourceMonitor(
        FakeProcess(), system_cpu_reader=read_system_cpu, sample_interval=0.005
    )
    aborted: list[bool] = []
    monitor.start()
    monitor.attach_abort(lambda: aborted.append(True))
    assert monitor.interrupted_event.wait(1)
    with pytest.raises(EngineFailure, match="system_cpu_limit_exceeded") as failure:
        monitor.check()
    assert aborted == [True]
    assert failure.value.metrics["cpu_limit_percent"] == 80.0
    assert failure.value.metrics["system_cpu_peak_percent"] == 80.0
    assert failure.value.metrics["process_cpu_peak_percent_machine"] == 20.0
    assert failure.value.metrics["rss_peak_mib"] == 128.0
    with pytest.raises(EngineFailure, match="system_cpu_limit_exceeded"):
        monitor.stop()


def test_inference_resource_monitor_fails_closed_when_measurement_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from woori.local_inference import InferenceResourceMonitor

    class FakeProcess:
        def cpu_percent(self, interval: float | None = None) -> float:
            return 12.0

        def memory_info(self) -> Any:
            return SimpleNamespace(rss=64 * 1024**2)

    monkeypatch.setattr("woori.local_inference.psutil.cpu_count", lambda: 8)
    calls = 0

    def read_system_cpu(*, interval: float | None = None) -> float:
        nonlocal calls
        calls += 1
        if calls == 1:
            return 10.0
        raise OSError("synthetic resource counter failure")

    monitor = InferenceResourceMonitor(
        FakeProcess(), system_cpu_reader=read_system_cpu, sample_interval=0.005
    )
    aborted: list[bool] = []
    monitor.start()
    monitor.attach_abort(lambda: aborted.append(True))
    assert monitor.interrupted_event.wait(1)
    with pytest.raises(EngineFailure, match="inference_resource_monitor_failed") as failure:
        monitor.check()
    assert aborted == [True]
    assert failure.value.metrics["cpu_limit_percent"] == 80.0
    with pytest.raises(EngineFailure, match="inference_resource_monitor_failed"):
        monitor.stop()


def test_llama_provider_closes_stream_on_cpu_limit_without_returning_partial_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from types import SimpleNamespace

    from woori import local_inference as local

    stream_started = threading.Event()
    stream_closed = threading.Event()

    class DelayedStream(httpx.SyncByteStream):
        def __iter__(self):
            stream_started.set()
            yield b'data: {"choices":[{"delta":{"content":"{"}}]}\n\n'
            while not stream_closed.wait(0.01):
                continue
            raise httpx.ReadError("client disconnected")

        def close(self) -> None:
            stream_closed.set()

    class FakeProcess:
        def cpu_percent(self, interval: float | None = None) -> float:
            return 120.0

        def memory_info(self) -> Any:
            return SimpleNamespace(rss=128 * 1024**2)

    cpu_calls = 0

    def read_system_cpu(*, interval: float | None = None) -> float:
        nonlocal cpu_calls
        cpu_calls += 1
        if cpu_calls == 1:
            return 12.0
        stream_started.wait(1)
        return 82.0

    base_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={})
        return httpx.Response(200, stream=DelayedStream())

    monkeypatch.setattr(local, "runtime", lambda: {
        "pid": 123, "model": "test.gguf", "engine": "mocked", "backend": "cpu",
        "gpu_layers": 0, "threads": 2,
    })
    monkeypatch.setattr(local.psutil, "Process", lambda _pid: FakeProcess())
    monkeypatch.setattr(local.psutil, "cpu_count", lambda: 12)
    monkeypatch.setattr(local.psutil, "cpu_percent", read_system_cpu)
    monkeypatch.setattr(local, "RESOURCE_SAMPLE_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(local, "auth_headers", lambda: {"Authorization": "Bearer test"})
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: base_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    context = {
        "language_code": "en", "sources": [{"id": "source-1", "evidence": "evidence"}],
        "keyword": "probe", "as_of": "2026-10-28", "instructions": "test only",
    }

    with pytest.raises(EngineFailure, match="system_cpu_limit_exceeded") as failure:
        LlamaCppProvider().generate(
            context,
            {"model": "test.gguf", "language_verified": True, "engine": "llamacpp", "threads": 2, "timeout_seconds": 5},
        )

    assert stream_closed.is_set()
    assert failure.value.metrics["system_cpu_peak_percent"] == 82.0


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
    from woori.secret_scan import contains_secret, contains_secret_in_http_response

    public_id = "00000000-0000-4000-8000-0000abcd0000"
    assert not contains_secret(public_id, "abcd")
    assert contains_secret(public_id + " password=abcd", "abcd")
    assert contains_secret(public_id, public_id)
    assert contains_secret("password=abcd", "abcd")
    assert not contains_secret_in_http_response("The test article was saved.", "test")
    assert contains_secret_in_http_response('{"refresh_token":"abcd"}', "abcd")
    assert contains_secret_in_http_response(
        "postgresql://woori:abcd@127.0.0.1:5432/app", "abcd"
    )


def test_fact_first_localization_renders_citations_from_source_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from woori import local_inference
    from woori.pipeline import render_localized_fact_section

    source = {
        "id": "src-1", "source_language": "en", "url": "https://example.org/report",
        "evidence": "The report covers 2026.",
    }
    registry = fact_ledger(source)[0]
    fact = {
        "fact_id": registry["fact_key"], "source_id": "src-1",
        "text": registry["source_excerpt"], "source_language": "en",
        "entities": registry["entities"], "numeric_values": registry["numeric_values"],
        "date_values": registry["date_values"], "citation_ids": ["src-1"],
    }
    monkeypatch.setattr(
        local_inference, "localized_translation",
        lambda text, target, glossary, entities, model, timeout, mode="translate", metrics_sink=None, claim_status="unverified": (
            "??? ??? ?? 2026" if text == source["evidence"]
            else "??? ??"
        ),
    )
    draft, validation = render_localized_fact_section(
        [fact], [source], "ko", "English topic", [], "Qwen3-4B-Q4_K_M.gguf", 120, True,
    )
    assert draft.body == "??? ??? ?? 2026 [source:src-1]"
    assert draft.source_ids == ["src-1"]
    assert draft.title.endswith("??? ??")
    assert validation["fact_checks"][fact["fact_id"]]["citation_linked"] is True
    assert draft._metrics["model_calls"] == 2


def test_fact_first_model_override_is_evaluation_only_and_bounded(lab: Any) -> None:
    conn, _api, _headers = lab
    keyword_id, _profile_ids = make_topic(lab)
    conn.execute(
        "UPDATE generation_settings SET provider='local',engine='llamacpp',model='Qwen3-1.7B-Q8_0.gguf'"
    )
    job = pipeline.enqueue(
        uuid.UUID(keyword_id), "fact-first-" + uuid.uuid4().hex,
        evaluation_only=True, evaluation_model="Qwen3-4B-Q4_K_M.gguf",
    )
    snapshots = conn.execute(
        "SELECT settings_snapshot FROM generation_targets WHERE run_id=%s", (job["id"],)
    ).fetchall()
    assert len(snapshots) == 4
    assert all(
        row["settings_snapshot"]["model"] == "Qwen3-4B-Q4_K_M.gguf"
        and row["settings_snapshot"]["evaluation_model_override"] is True
        and row["settings_snapshot"]["evaluation_only"] is True
        for row in snapshots
    )
    assert conn.execute(
        "SELECT 1 FROM audit_events WHERE run_id=%s AND event_type='research.evaluation.model.override'",
        (job["id"],),
    ).fetchone()
    candidate = pipeline.enqueue(
        uuid.UUID(keyword_id), "candidate-model-" + uuid.uuid4().hex,
        evaluation_only=True, evaluation_model="Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    )
    candidate_models = conn.execute(
        "SELECT settings_snapshot FROM generation_targets WHERE run_id=%s", (candidate["id"],)
    ).fetchall()
    assert all(
        row["settings_snapshot"]["model"] == "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
        and row["settings_snapshot"]["evaluation_model_override"] is True
        for row in candidate_models
    )
    with pytest.raises(EngineFailure, match="evaluation_model_override_blocked"):
        pipeline.enqueue(
            uuid.UUID(keyword_id), "unsafe-" + uuid.uuid4().hex,
            evaluation_only=False, evaluation_model="Qwen3-4B-Q4_K_M.gguf",
        )

    with pytest.raises(EngineFailure, match="evaluation_model_override_blocked"):
        pipeline.enqueue(
            uuid.UUID(keyword_id), "unsafe-candidate-" + uuid.uuid4().hex,
            evaluation_only=False, evaluation_model="Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        )
    conn.execute(
        "UPDATE generation_settings SET model='Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf'"
    )
    with pytest.raises(EngineFailure, match="evaluation_only_model_blocked"):
        pipeline.enqueue(
            uuid.UUID(keyword_id), "unsafe-configured-candidate-" + uuid.uuid4().hex,
            evaluation_only=False,
        )


def test_evaluation_and_operations_have_separate_daily_quotas(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _api, _headers = lab
    monkeypatch.setattr(
        pipeline, "evaluation_quota_priority",
        lambda _conn, _keyword_id: {"pending": False, "request_is_sec": False},
    )
    first_keyword, profiles = make_topic(lab)
    second_keyword, _ = make_topic(lab)
    third_keyword, _ = make_topic(lab)
    fourth_keyword, _ = make_topic(lab)
    conn.execute(
        "UPDATE generation_settings SET provider='local',engine='llamacpp',model='Qwen3-1.7B-Q8_0.gguf'"
    )
    usage = conn.execute(
        """SELECT t.profile_id,
        count(*) FILTER (WHERE j.evaluation_only)::int AS evaluation_count,
        count(*) FILTER (WHERE NOT j.evaluation_only)::int AS operations_count
        FROM generation_targets t JOIN generation_jobs j ON j.run_id=t.run_id
        WHERE j.created_at>=date_trunc('day',now()) GROUP BY t.profile_id"""
    ).fetchall()
    baseline = {row["profile_id"]: (row["evaluation_count"], row["operations_count"]) for row in usage}
    for profile in profiles:
        conn.execute(
            "UPDATE generation_settings SET daily_limit=%s,evaluation_daily_limit=%s WHERE profile_id=%s",
            (baseline.get(profile, (0, 0))[1] + 1, baseline.get(profile, (0, 0))[0] + 1, profile),
        )
    pipeline.enqueue(
        uuid.UUID(first_keyword), "limited-eval-" + uuid.uuid4().hex,
        evaluation_only=True, evaluation_model="Qwen3-4B-Q4_K_M.gguf",
    )
    pipeline.enqueue(uuid.UUID(second_keyword), "ops-quota-independent-" + uuid.uuid4().hex)
    with pytest.raises(EngineFailure, match="daily_evaluation_limit"):
        pipeline.enqueue(
            uuid.UUID(third_keyword), "over-limit-eval-" + uuid.uuid4().hex,
            evaluation_only=True, evaluation_model="Qwen3-4B-Q4_K_M.gguf",
        )
    with pytest.raises(EngineFailure, match="daily_generation_limit"):
        pipeline.enqueue(uuid.UUID(fourth_keyword), "over-limit-ops-" + uuid.uuid4().hex)


def test_evaluation_enqueue_fails_closed_without_database_isolation(lab: Any) -> None:
    conn, _api, _headers = lab
    keyword_id, _profiles = make_topic(lab)
    conn.execute("UPDATE generation_settings SET provider='local',engine='llamacpp'")
    conn.execute("UPDATE pipeline_controls SET evaluation_isolated=false")
    with pytest.raises(EngineFailure, match="evaluation_database_isolation_required"):
        pipeline.enqueue(
            uuid.UUID(keyword_id), "shared-db-eval-" + uuid.uuid4().hex,
            evaluation_only=True, evaluation_model="Qwen3-4B-Q4_K_M.gguf",
        )


def test_evaluation_enqueue_rejects_same_physical_database(lab: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, _api, _headers = lab
    keyword_id, _profiles = make_topic(lab)
    conn.execute("UPDATE generation_settings SET provider='local',engine='llamacpp'")
    conn.execute("UPDATE pipeline_controls SET evaluation_isolated=true")
    monkeypatch.setattr(pipeline, "evaluation_database_isolated", _ORIGINAL_EVALUATION_DB_ISOLATION)
    monkeypatch.setenv("WOORI_OPERATION_DATABASE_URL", conn.info.dsn)
    with pytest.raises(EngineFailure, match="evaluation_database_isolation_required"):
        pipeline.enqueue(
            uuid.UUID(keyword_id), "same-physical-db-eval-" + uuid.uuid4().hex,
            evaluation_only=True, evaluation_model="Qwen3-4B-Q4_K_M.gguf",
        )


def test_fact_first_quote_gate_holds_twenty_five_word_source_copy() -> None:
    words = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive"
    draft = Draft(
        title="Source review", body=words, summary="Internal test only.",
        keywords=["source"], source_ids=["source-1"],
    )
    result = pipeline.direct_quote_gate(draft, [{"evidence": words}])
    assert result == {"no_mass_direct_quote": False, "longest_source_overlap_words": 25}


def test_same_language_local_edit_still_checks_target_language() -> None:
    fact = {
        "fact_key": "fact-1", "source_language": "en", "source_excerpt": "An update covers 2026.",
        "numeric_values": ["2026"], "entities": [], "citation_ids": ["source-1"],
    }
    result = localize_fact(
        fact, "en", translator=lambda *_args: "한국어 내용 2026", force_local=True,
    )
    assert result["status"] == "quality_held"
    assert result["checks"]["language_matches"] is False


def test_taiwan_minguo_date_matches_its_gregorian_equivalent() -> None:
    assert numbers("\u6c11\u570b115\u5e747\u67081\u65e5") == numbers("2026-07-01")
    assert numbers("115\u5e747\u67081\u65e5") == numbers("July 1, 2026")


def test_section_claim_gate_blocks_internal_fact_markers() -> None:
    from woori.grounding import extract_facts
    from woori.pipeline import section_response_valid

    source = {"id": "source-1", "evidence": "A reviewed source states a proposal is planned."}
    facts = extract_facts([source])
    draft = Draft(
        title="A reviewed proposal",
        body="FACT-F1: A reviewed source states a proposal is planned. [source:source-1]",
        summary="A proposal remains under review.",
        keywords=["proposal"],
        source_ids=["source-1"],
    )
    result = section_response_valid(draft, facts, {"source-1"}, "2026-10-28")
    assert not result["passed"]
    assert not result["checks"]["no_internal_fact_markers"]


def test_claim_status_cannot_be_promoted_without_reviewed_exact_evidence() -> None:
    from woori.claim_status import prepare_claim_for_generation

    source_fact = {"fact_id": "fact-1", "text": "The ministry proposed the plan."}
    assert prepare_claim_for_generation(source_fact)["claim_status"] == "unverified"
    assert prepare_claim_for_generation({
        **source_fact,
        "claim_status": "proposed",
        "claim_status_basis_excerpt": "proposed the plan",
        "claim_status_reviewed": True,
    })["claim_status"] == "proposed"
    with pytest.raises(ValueError, match="claim_status_evidence_missing"):
        prepare_claim_for_generation({**source_fact, "claim_status": "enacted"})
    with pytest.raises(ValueError, match="claim_status_invalid"):
        prepare_claim_for_generation({**source_fact, "claim_status": "passed"})


def test_claim_lifecycle_status_gate_rejects_unearned_certainty() -> None:
    from woori.claim_status import lifecycle_status_violations

    proposed = [{"claim_status": "proposed"}]
    assert lifecycle_status_violations("The measure was proposed.", proposed) == []
    assert lifecycle_status_violations("The measure was approved and enacted.", proposed)
    unverified = [{"claim_status": "unverified"}]
    assert lifecycle_status_violations("The amount was paid.", unverified)
    assert lifecycle_status_violations("The measure will take effect.", unverified)
    assert lifecycle_status_violations("The source records a proposal.", unverified)
    approved = [{"claim_status": "approved"}]
    assert lifecycle_status_violations("The measure was approved.", approved) == []
    assert lifecycle_status_violations("The measure was enacted.", approved)
    enacted = [{"claim_status": "enacted"}]
    assert lifecycle_status_violations("The measure took effect.", enacted) == []
    assert lifecycle_status_violations("The amount was paid.", enacted)
