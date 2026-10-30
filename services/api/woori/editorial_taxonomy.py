"""Extensible editorial categories and deterministic label suggestions."""

from __future__ import annotations

from typing import Any

# Registry is deliberately data-shaped: new categories can be added without
# changing the import contract or hard-coding category branches in workflows.
EDITORIAL_CATEGORIES: tuple[dict[str, Any], ...] = (
    {"slug": "economy", "name_ko": "경제", "name_en": "Economy", "deduplication_group": "macro-markets"},
    {"slug": "finance", "name_ko": "금융", "name_en": "Finance", "deduplication_group": "macro-markets"},
    {"slug": "stocks", "name_ko": "주식", "name_en": "Stocks", "deduplication_group": "macro-markets"},
    {"slug": "crypto", "name_ko": "암호화폐", "name_en": "Crypto", "deduplication_group": "digital-assets"},
    {"slug": "technology", "name_ko": "IT", "name_en": "Technology", "deduplication_group": "technology"},
    {"slug": "semiconductors", "name_ko": "반도체", "name_en": "Semiconductors", "deduplication_group": "technology"},
    {"slug": "artificial-intelligence", "name_ko": "인공지능", "name_en": "Artificial Intelligence", "deduplication_group": "technology"},
    {"slug": "policy", "name_ko": "정치·정책", "name_en": "Politics & Policy", "deduplication_group": "public-policy"},
    {"slug": "sports", "name_ko": "스포츠", "name_en": "Sports", "deduplication_group": "sports"},
    {"slug": "entertainment", "name_ko": "엔터테인먼트", "name_en": "Entertainment", "deduplication_group": "entertainment"},
)

ISSUE_LABELS = {"ko": "이슈", "en": "Issues", "ja": "話題", "zh-CN": "热点"}
CATEGORY_LABELS = {
    "economy": {"ko": "경제", "en": "Economy", "ja": "経済", "zh-CN": "经济"},
    "finance": {"ko": "금융", "en": "Finance", "ja": "金融", "zh-CN": "金融"},
    "stocks": {"ko": "주식", "en": "Stocks", "ja": "株式", "zh-CN": "股票"},
    "crypto": {"ko": "암호화폐", "en": "Crypto", "ja": "暗号資産", "zh-CN": "加密货币"},
    "technology": {"ko": "IT", "en": "Technology", "ja": "テクノロジー", "zh-CN": "科技"},
    "semiconductors": {"ko": "반도체", "en": "Semiconductors", "ja": "半導体", "zh-CN": "半导体"},
    "artificial-intelligence": {"ko": "인공지능", "en": "Artificial Intelligence", "ja": "人工知能", "zh-CN": "人工智能"},
    "policy": {"ko": "정치·정책", "en": "Policy", "ja": "政策", "zh-CN": "政策"},
    "sports": {"ko": "스포츠", "en": "Sports", "ja": "スポーツ", "zh-CN": "体育"},
    "entertainment": {"ko": "엔터테인먼트", "en": "Entertainment", "ja": "エンタメ", "zh-CN": "娱乐"},
}


def category_registry() -> list[dict[str, Any]]:
    return [dict(item) for item in EDITORIAL_CATEGORIES]


def suggested_labels(category: str, language_code: str, *, google_trends_based: bool) -> list[str]:
    labels: list[str] = []
    if google_trends_based and language_code in ISSUE_LABELS:
        labels.append(ISSUE_LABELS[language_code])
    category_label = CATEGORY_LABELS.get(category, {}).get(language_code)
    if category_label and category_label not in labels:
        labels.append(category_label)
    return labels


def language_candidates(region: str | None, explicit_relevance: dict[str, str] | None = None) -> dict[str, Any]:
    """Return suggestions only; region alone never authorizes publication."""
    normalized = (region or "").strip().upper()
    direct = {"KR": "ko", "US": "en", "JP": "ja", "CN": "zh-CN"}.get(normalized)
    reasons = dict(explicit_relevance or {})
    if direct and direct not in reasons:
        reasons[direct] = "region_match_requires_editorial_relevance_review"
    if normalized in {"TW", "HK", "SG"}:
        regional_note = "region_alone_does_not_select_simplified_chinese"
    elif not normalized:
        regional_note = "source_region_unavailable"
    else:
        regional_note = "region_is_context_not_language_or_audience_proof"
    return {
        "source_region": normalized or None,
        "suggested_languages": sorted(reasons),
        "reader_relevance_reasons": reasons,
        "regional_note": regional_note,
        "publication_authorized": False,
    }
