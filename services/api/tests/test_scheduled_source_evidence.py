from __future__ import annotations

from uuid import uuid4

import httpx
import woori.scheduled_source_evidence as source_evidence
from woori import external_policy


def test_capture_catalog_is_exact_and_unknown_urls_are_never_fetched() -> None:
    exact = "https://www.nenryo-teigakuhikisage.go.jp/"
    assert exact in source_evidence._CATALOG
    for changed in (
        "https://www.nenryo-teigakuhikisage.go.jp/other",
        "https://www.nenryo-teigakuhikisage.go.jp/?redirect=https://example.com",
        "https://nenryo-teigakuhikisage.go.jp/",
        "http://www.nenryo-teigakuhikisage.go.jp/",
    ):
        assert source_evidence._fetch(changed, uuid4())["status"] == "not_in_reviewed_catalog"


def test_page_parser_keeps_title_date_and_visible_source_spans() -> None:
    parser = source_evidence._PageText()
    parser.feed(
        "<html><head><title>\u652f\u7d66\u5358\u4fa1</title><meta property='article:modified_time' "
        "content='2026-10-28'></head><body><nav>not evidence</nav>"
        "<h2>2026\u5e7410\u670829\u65e5\u4ee5\u964d\u306e\u652f\u7d66\u5358\u4fa1</h2>"
        "<p>\u30ac\u30bd\u30ea\u30f3 52.4\u5186/L</p>"
        "<script>hidden()</script></body></html>"
    )
    if parser.current:
        parser._flush()
    assert "\u652f\u7d66\u5358\u4fa1" in "".join(parser.title)
    assert parser.updated_at == "2026-10-28"
    date_text = "2026" + chr(0x5e74) + "10" + chr(0x6708) + "29" + chr(0x65e5)
    number_text = "52.4" + chr(0x5186) + "/L"
    assert source_evidence._DATE_RE.findall(date_text) == [date_text]
    assert source_evidence._NUMBER_RE.findall(date_text + " " + number_text) == ["2026", "10", "29", number_text]
    assert parser.paragraphs == [
        "2026\u5e7410\u670829\u65e5\u4ee5\u964d\u306e\u652f\u7d66\u5358\u4fa1",
        "\u30ac\u30bd\u30ea\u30f3 52.4\u5186/L",
    ]


def test_claim_numbers_are_checked_only_inside_an_exact_linked_source_span() -> None:
    number = "52.4" + chr(0x5186) + "/L"
    claim = {"claim_id": "C1", "claim": number, "evidence_excerpt": "missing excerpt"}
    _, check = source_evidence._claim_fact_check(claim, ["unrelated 52.4" + chr(0x5186) + "/L"])
    assert check["evidence_excerpt_exactly_present"] is False
    assert check["numbers"] == [{"value": number, "present": False}]


def test_reuse_terms_are_not_inferred_from_official_site_or_source_access() -> None:
    proof = source_evidence._CATALOG["https://www.nenryo-teigakuhikisage.go.jp/"]
    assert proof["provider"] == "japan_energy_subsidy_site"
    provider = external_policy.PROVIDERS[proof["provider"]]
    assert provider["paths_by_host"][proof["source_host"]] == ("/",)
    assert provider["zero_cost_reviewed"] is True
    assert "rights stay unknown" in provider["commercial_use"]


def test_external_policy_allows_only_the_exact_public_document_path(monkeypatch) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    external_policy._authorize(
        "japan_energy_subsidy_site",
        "source_collection",
        httpx.Request("GET", "https://www.nenryo-teigakuhikisage.go.jp/"),
    )
    for url in (
        "https://www.nenryo-teigakuhikisage.go.jp/other",
        "https://www.nenryo-teigakuhikisage.go.jp/?x=1",
    ):
        try:
            external_policy._authorize(
                "japan_energy_subsidy_site", "source_collection", httpx.Request("GET", url)
            )
        except external_policy.ExternalCallBlocked as exc:
            assert str(exc) == "destination_or_method_not_allowlisted"
        else:
            raise AssertionError("unlisted document path must be blocked")
