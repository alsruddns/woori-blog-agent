import pytest
from woori.article_quality import inspect_trend_article


@pytest.mark.parametrize(
    ("language", "leaked_sentence", "clean_sentence"),
    [
        ("en", "We analyzed the collected data for this report.", "The ministry published a new order on Tuesday."),
        ("ko", "수집된 데이터를 분석한 결과입니다.", "정부는 화요일 새 행정명령을 발표했습니다."),
        ("ja", "収集したデータを分析した結果です。", "政府は火曜日に新たな命令を発表しました。"),
        ("de", "Wir haben Daten gesammelt und analysiert.", "Die Behörde veröffentlichte am Dienstag eine neue Anordnung."),
        ("pt-BR", "Analisamos os dados coletados para este relatório.", "O ministério publicou uma nova medida na terça-feira."),
        ("vi", "Chúng tôi đã phân tích dữ liệu thu thập được.", "Cơ quan công bố quyết định mới vào thứ Ba."),
    ],
)
def test_process_narration_is_flagged_and_clean_event_copy_is_not(language, leaked_sentence, clean_sentence):
    leaked = inspect_trend_article("Agency announces a dated policy change", f"## Main\n\n{leaked_sentence}", language)
    clean = inspect_trend_article("Agency announces a dated policy change", f"## Main\n\n{clean_sentence}", language)
    assert "no_internal_process_leakage" in leaked["issues"]
    assert "no_internal_process_leakage" not in clean["issues"]
    assert leaked["semantic_verification"] == clean["semantic_verification"] == "not_performed"


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("en", "Why NVIDIA is trending"),
        ("ko", "왜 엔비디아 검색어가 급상승했나"),
        ("ja", "なぜエヌビディアが急上昇しているのか"),
        ("de", "Warum NVIDIA im Trend liegt"),
        ("pt-BR", "Por que NVIDIA está em alta"),
        ("vi", "Vì sao NVIDIA đang thịnh hành"),
    ],
)
def test_keyword_popularity_titles_are_not_news_articles(language, title):
    result = inspect_trend_article(title, "## Details\n\nThe report discusses a search phrase.", language)
    assert "event_not_keyword_report" in result["issues"]


def test_google_trends_product_news_is_not_misclassified_as_process_leakage():
    result = inspect_trend_article(
        "Google Trends releases a public search report",
        "## Report\n\nGoogle Trends published a new report describing changes to its search-interest page.",
        "en",
    )
    assert result["trends_service_is_reported_subject"] is True
    assert "no_internal_process_leakage" not in result["issues"]
    assert "event_not_keyword_report" not in result["issues"]


def test_repeated_filler_reduces_information_density():
    paragraph = "It remains to be seen what happens next."
    result = inspect_trend_article(
        "Agency announces a dated policy change",
        f"## Details\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}",
        "en",
    )
    assert "information_density" in result["issues"]


def test_unconfigured_trends_locale_fails_closed():
    result = inspect_trend_article("A specific event", "A factual report.", "xx-ZZ")
    assert result["supported_locale"] is False
    assert result["issues"] == ["trend_locale_not_configured"]


def test_trends_quality_block_is_applied_to_deterministic_assessment():
    from datetime import UTC, datetime, timedelta

    from woori.ai import Draft
    from woori.article_quality import evaluate

    source = {
        "id": "src-1", "url": "https://example.gov/notice", "source_name": "Public Agency",
        "evidence": "The agency published a dated notice describing its new filing rule.",
        "rights": "Review required", "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    draft = Draft(
        title="Agency publishes a new filing rule",
        body=("## What changed\n\nWe analyzed the collected data for this report. [source:src-1]\n\n"
              "## What the notice says\n\nThe notice describes the stated filing rule and effective date. [source:src-1]\n\n"
              "## Scope\n\nThe notice does not establish additional changes beyond its text. [source:src-1]"),
        summary="A dated filing rule announced by the public agency.",
        keywords=["filing rule"], source_ids=["src-1"],
    )
    result = evaluate(
        draft, [source], "en", datetime.now(UTC).date().isoformat(), 3,
        google_trends_based=True,
    )
    assert not result["checks"]["trend_no_internal_process_leakage"]
    assert result["trend_article_quality"]["issues"]
    assert result["human_review_required"] and result["publish_ready"] is False
