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


def test_reviewed_fed_statement_catalog_is_resource_bound_not_import_id_bound() -> None:
    url = 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm'
    assert source_evidence._catalog_entry(url)['provider'] == 'federal_reserve'
    assert source_evidence._catalog_entry(url + '?redirect=1') is None
    assert source_evidence._catalog_entry(url.replace('www.federalreserve.gov','evil.example')) is None


def test_ons_source_catalog_is_exact_and_reuse_terms_are_host_bound() -> None:
    from woori.topics import OFFICIAL_SOURCE_HOSTS

    exact = "https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026"
    assert exact in source_evidence._CATALOG
    assert "www.ons.gov.uk" in OFFICIAL_SOURCE_HOSTS
    for changed in (
        exact + "?query=1",
        exact + "/other",
        "http://" + exact.removeprefix("https://"),
        "https://other.ons.gov.uk" + exact.removeprefix("https://www.ons.gov.uk"),
    ):
        assert source_evidence._fetch(changed, uuid4())["status"] == "not_in_reviewed_catalog"
    assert source_evidence._ons_reuse_terms_allowed(
        "All content is available under the Open Government Licence v3.0, except where otherwise stated.",
        "Most content on this website is published under the Open Government Licence (OGL). "
        "Reproduction of information is subject to the terms of the OGL. "
        "Some photographs, illustrations and videos use third-party copyright.",
    )
    assert not source_evidence._ons_reuse_terms_allowed(
        "All content is available under the Open Government Licence v3.0.",
        "Some content is covered by an open licence.",
    )


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


def test_page_parser_records_only_visible_footer_license_notice() -> None:
    parser = source_evidence._PageText()
    parser.feed(
        "<html><head><title>ONS release</title></head><body><p>Article fact.</p>"
        "<footer><p>Open Government Licence v3.0 except where otherwise stated</p>"
        "<script>fake licence</script></footer></body></html>"
    )
    if parser.current:
        parser._flush()
    assert "Open Government Licence v3.0" in "".join(parser.footer)
    assert "fake licence" not in "".join(parser.footer)
    assert parser.paragraphs == ["Article fact."]


def test_ons_release_date_is_stored_as_a_date_without_inventing_a_time() -> None:
    assert source_evidence._ons_release_date(
        "Release date: 21 October 2026 Next release: 20 November 2026"
    ) == "2026-10-21"
    assert source_evidence._ons_release_date("Publication date not present") is None


def test_normalized_claim_quantities_are_checked_only_inside_exact_source_span() -> None:
    number = "52.4" + chr(0x5186) + "/L"
    claim = {"claim_id": "C1", "claim": number, "evidence_excerpt": "missing excerpt"}
    _, check = source_evidence._claim_fact_check(claim, ["unrelated 52.4" + chr(0x5186) + "/L"])
    assert check["evidence_excerpt_exactly_present"] is False
    assert check["normalized_quantities"] == [{"kind": "number", "value": "52.4", "present": False}]
    assert check["all_numeric_units_and_dates_match"] is False


def test_claim_capture_normalizes_korean_currency_percent_and_month_units() -> None:
    excerpt = "Borrowing was £1.8 billion in September 2026; 7.7% more than a year earlier."
    claim = {
        "claim_id": "C1",
        "claim": "2026년 9월 차입은 18억 파운드로 7.7% 증가했다.",
        "evidence_excerpt": excerpt,
    }
    _, check = source_evidence._claim_fact_check(claim, [excerpt])
    assert check["evidence_excerpt_exactly_present"] is True
    assert check["all_numeric_units_and_dates_match"] is True


def test_claim_capture_rejects_currency_unit_and_month_mismatch() -> None:
    excerpt = "Borrowing was £1.8 billion in September 2026."
    claim = {
        "claim_id": "C1",
        "claim": "2026년 8월 차입은 19억 파운드였다.",
        "evidence_excerpt": excerpt,
    }
    _, check = source_evidence._claim_fact_check(claim, [excerpt])
    assert check["evidence_excerpt_exactly_present"] is True
    assert check["all_numeric_units_and_dates_match"] is False


def test_reuse_terms_are_not_inferred_from_official_site_or_source_access() -> None:
    proof = source_evidence._CATALOG["https://www.nenryo-teigakuhikisage.go.jp/"]
    assert proof["provider"] == "japan_energy_subsidy_site"
    provider = external_policy.PROVIDERS[proof["provider"]]
    assert provider["paths_by_host"][proof["source_host"]] == ("/",)
    assert provider["zero_cost_reviewed"] is True
    assert "rights stay unknown" in provider["commercial_use"]


def test_ons_provider_has_only_two_reviewed_paths_and_no_write_methods() -> None:
    provider = external_policy.PROVIDERS["ons_official_statistics"]
    assert provider["hosts"] == {"www.ons.gov.uk"}
    assert provider["methods"] == {"GET"}
    assert provider["operations"] == {"source_collection"}
    assert provider["rph"] == 6
    assert provider["paths_by_host"]["www.ons.gov.uk"] == (
        "/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026",
        "/help/terms-conditions",
    )


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


def test_external_policy_allows_only_reviewed_ons_source_and_terms_paths(monkeypatch) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    allowed = (
        "https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/publicsectorfinance/bulletins/publicsectorfinances/september2026",
        "https://www.ons.gov.uk/help/terms-conditions",
    )
    for url in allowed:
        external_policy._authorize(
            "ons_official_statistics", "source_collection", httpx.Request("GET", url)
        )
    for url in (
        "https://www.ons.gov.uk/help/other",
        "https://other.ons.gov.uk/help/terms-conditions",
        "https://www.ons.gov.uk/help/terms-conditions?next=https://example.org",
    ):
        try:
            external_policy._authorize(
                "ons_official_statistics", "source_collection", httpx.Request("GET", url)
            )
        except external_policy.ExternalCallBlocked:
            pass
        else:
            raise AssertionError("unreviewed ONS path or query must be blocked")
