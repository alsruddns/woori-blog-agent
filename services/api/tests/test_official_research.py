from __future__ import annotations

from typing import Self

import httpx
import pytest
from woori import external_policy, official_research


def test_taiwan_official_source_policy_is_closed_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    external_policy._windows.clear()
    external_policy._authorize(
        "taiwan_official_documents",
        "source_collection",
        httpx.Request("GET", CATALOG_URL),
    )
    for request in (
        httpx.Request(
            "GET", "https://evil.example/Page/448DE008087A1971/5020ed44-2196-4da0-9dbe-fe6ae7f44afc"
        ),
        httpx.Request("GET", "https://www.ey.gov.tw/Page/unknown"),
        httpx.Request("POST", CATALOG_URL),
        httpx.Request(
            "GET", "http://www.ey.gov.tw/Page/448DE008087A1971/5020ed44-2196-4da0-9dbe-fe6ae7f44afc"
        ),
    ):
        with pytest.raises(external_policy.ExternalCallBlocked):
            external_policy._authorize("taiwan_official_documents", "source_collection", request)


def test_taiwan_official_source_hourly_cap_survives_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        def __init__(self, row: dict[str, int] | None = None) -> None:
            self.row = row

        def fetchone(self) -> dict[str, int] | None:
            return self.row

    class FakeConnection:
        def __init__(self, count: int) -> None:
            self.count = count
            self.inserted = False

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
            if "SELECT count(*) AS n FROM audit_events" in query:
                return FakeResult({"n": self.count})
            if "INSERT INTO audit_events" in query:
                self.inserted = True
            return FakeResult()

    from woori import db

    blocked = FakeConnection(8)
    monkeypatch.setattr(db, "connection", lambda: blocked)
    with pytest.raises(
        external_policy.FreeQuotaExceeded, match="durable_free_hourly_call_limit_reached"
    ):
        external_policy._reserve_taiwan_official_call("www.ey.gov.tw", "GET", 8)
    assert not blocked.inserted

    available = FakeConnection(7)
    monkeypatch.setattr(db, "connection", lambda: available)
    external_policy._reserve_taiwan_official_call("www.ey.gov.tw", "GET", 8)
    assert available.inserted


CATALOG_URL = "https://www.ey.gov.tw/Page/448DE008087A1971/5020ed44-2196-4da0-9dbe-fe6ae7f44afc"


def test_fact_span_extraction_requires_all_markers_and_keeps_exact_sentence() -> None:
    text = (
        "方案包括專業加給及主管職務加給各定額調增2,000元，待遇通案調增4％。其餘背景未進入本次抽取。"
    )
    spans = official_research._sentence_spans(text, (("2,000元", "4％"),))
    assert spans == ["方案包括專業加給及主管職務加給各定額調增2,000元，待遇通案調增4％。"]
    with pytest.raises(
        official_research.OfficialResearchBlocked, match="required_source_fact_span_not_found"
    ):
        official_research._sentence_spans(text, (("2,000元", "不存在"),))


def test_visible_text_ignores_navigation_and_scripts() -> None:
    parser = official_research._VisibleText()
    parser.feed("<nav>menu</nav><script>fake 99</script><h1>Title</h1><p>Verified 42.</p>")
    assert "menu" not in parser.text()
    assert "fake" not in parser.text()
    assert "Verified 42." in parser.text()


def test_roc_date_is_normalized_without_changing_source_excerpt() -> None:
    source_text = "行政院方案自115年7月1日起生效。"
    fact = {
        "source_excerpt": source_text,
        "date_values": [],
    }
    typed = official_research._typed_fact(fact)
    assert typed["date_values"] == ["DATE:2026-07-01"]
    assert typed["source_excerpt"] == source_text


def test_legislative_source_facts_may_appear_in_separate_report_points() -> None:
    text = (
        "一、115年度中央政府總預算追加預算案係於9月提出。\n"
        "二、預算審查結果未經總統公布，尚無法定預算數前即送出追加預算案。\n"
        "四、軍公教人員待遇調整尚缺乏明確法制及客觀量化基準。"
    )
    spans = official_research._sentence_spans(text, official_research.CATALOG[2]["markers"])
    assert len(spans) == 3
    assert all(span in text for span in spans)


def test_catalog_is_scoped_to_matching_taiwan_topic() -> None:
    assert len(official_research.CATALOG) <= official_research.MAX_DOCUMENTS_PER_RUN
    assert all(
        item["host"] in external_policy.PROVIDERS["taiwan_official_documents"]["hosts"]
        for item in official_research.CATALOG
    )
    assert {item["comparison_group"] for item in official_research.CATALOG} == {
        "taiwan-government-pay-proposal",
        "taiwan-legislative-budget-review",
    }
