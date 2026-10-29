"""Deterministic, evidence-aware SEO metadata and pre-publication checks.

These checks report editorial work to review; they do not predict ranking or
replace factual, rights, or human editorial review.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

SeoCheckStatus = Literal["ready", "review", "not_measured"]


class SeoSource(BaseModel):
    title: str = Field(default="", max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    official_status: Literal["verified", "unverified", "not_applicable"] = "unverified"

    @field_validator("url")
    @classmethod
    def safe_source_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("seo_source_url_must_be_https")
        return value.strip()


class EditorialSeoMetadata(BaseModel):
    """Projection of existing editorial metadata; missing values stay unknown."""

    language_code: Literal["ko", "en", "ja", "zh-CN"]
    target_region: str | None = Field(default=None, max_length=80)
    search_intent: Literal["informational", "navigational", "transactional", "commercial"] | None = None
    primary_keyword: str | None = Field(default=None, max_length=80)
    related_terms: list[str] = Field(default_factory=list, max_length=6)
    seo_title_candidates: list[str] = Field(default_factory=list, max_length=5)
    seo_title: str = Field(min_length=1, max_length=500)
    search_description: str = Field(default="", max_length=500)
    core_question: str | None = Field(default=None, max_length=500)
    core_answer: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=120)
    blogger_labels: list[str] = Field(default_factory=list, max_length=20)
    author: str | None = Field(default=None, max_length=160)
    sources: list[SeoSource] = Field(default_factory=list, max_length=30)
    official_sources: list[SeoSource] = Field(default_factory=list, max_length=30)
    fact_verified_at: datetime | None = None
    editorial_status: str = Field(default="unknown", max_length=80)

    @field_validator("related_terms", "blogger_labels", "seo_title_candidates")
    @classmethod
    def compact_unique_values(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("seo_metadata_values_must_be_unique")
        return normalized


class SearchConsoleSnapshot(BaseModel):
    """Future GSC response shape; nullable values are never fabricated."""

    source: Literal["google_search_console"] = "google_search_console"
    measured_at: datetime | None = None
    impressions: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    ctr: float | None = Field(default=None, ge=0, le=1)
    average_position: float | None = Field(default=None, ge=0)
    queries: list[str] = Field(default_factory=list)
    country: str | None = None
    index_status: str | None = None


def evaluate_seo_readiness(
    metadata: EditorialSeoMetadata,
    *,
    title: str,
    plain_text: str,
    safe_html: str,
    source_body: str = "",
    body_format: str = "markdown",
) -> list[dict[str, str]]:
    """Return actionable checks without aggregating them into a ranking score."""
    checks: list[dict[str, str]] = []

    def add(key: str, status: SeoCheckStatus, message: str) -> None:
        checks.append({"key": key, "status": status, "message": message})

    exact_title = " ".join(metadata.seo_title.casefold().split()) == " ".join(title.casefold().split())
    add("title_matches_article", "ready" if exact_title else "review",
        "검색 제목이 실제 게시 제목과 같습니다." if exact_title else "검색 제목과 게시 제목의 차이를 검토하세요.")
    add("search_description", "ready" if metadata.search_description.strip() else "review",
        "검색 설명이 준비되어 있습니다." if metadata.search_description.strip() else "게시글별 검색 설명이 비어 있습니다.")
    if metadata.primary_keyword:
        occurrences = len(re.findall(re.escape(metadata.primary_keyword), plain_text, flags=re.IGNORECASE))
        add("primary_term", "ready" if occurrences else "review",
            f"핵심 표현이 본문에 {occurrences}회 있습니다. 반복의 자연스러움은 사람이 확인해야 합니다." if occurrences else "핵심 검색어가 본문에 없어 제목·본문의 검색 의도 일치를 검토하세요.")
    else:
        add("primary_term", "not_measured", "핵심 검색어가 지정되지 않았습니다.")
    add("search_intent", "ready" if metadata.search_intent else "not_measured",
        "검색 의도가 기록되어 있습니다." if metadata.search_intent else "검색 의도는 아직 기록되지 않았습니다.")
    h2_count = len(re.findall(r"<h2(?:\s|>)", safe_html, flags=re.IGNORECASE))
    has_h1 = bool(re.search(r"<h1(?:\s|>)", safe_html, flags=re.IGNORECASE))
    add("heading_structure", "ready" if h2_count and not has_h1 else "review",
        "본문 소제목 구조가 있으며 게시글 제목과 중복 H1이 없습니다." if h2_count and not has_h1 else "본문의 H2 소제목 구조와 게시글 제목 중복 여부를 확인하세요.")
    link_count = len(re.findall(r"<a\s+href=", safe_html, flags=re.IGNORECASE))
    has_source_metadata = bool(metadata.sources or metadata.official_sources)
    add("source_links", "ready" if has_source_metadata and link_count else "review",
        "출처 정보와 본문 링크가 있습니다. 링크의 내용과 주장은 사람이 대조해야 합니다." if has_source_metadata and link_count else "확인 가능한 출처 정보와 본문 링크를 연결하세요.")
    add("link_targets", "not_measured", "외부 링크의 실제 응답과 문서 내용은 조회하지 않았습니다.")
    add("claim_source_mapping", "not_measured", "문장별 주장과 근거의 의미 일치는 별도 사실 검토가 필요합니다.")
    official_unverified = any(source.official_status != "verified" for source in metadata.official_sources)
    add("official_source_status", "review" if official_unverified else ("ready" if metadata.official_sources else "not_measured"),
        "공식 출처 여부가 모두 확인되었습니다." if metadata.official_sources and not official_unverified else "출처의 공식성은 저장된 근거만으로 확인되지 않았습니다." if metadata.official_sources else "출처가 제공되지 않아 공식성은 미측정입니다.")
    unsafe_alt = body_format == "html" and bool(re.search(r"<img\b(?![^>]*\balt\s*=)[^>]*>", source_body, flags=re.IGNORECASE))
    unsafe_alt = unsafe_alt or (body_format == "html" and bool(re.search(r"<img\b", source_body, flags=re.IGNORECASE)) and not re.search(r"<img\b", safe_html, flags=re.IGNORECASE))
    add("image_alt", "review" if unsafe_alt else ("ready" if "<img" in safe_html else "not_measured"),
        "이미지 대체 텍스트를 보완하세요." if unsafe_alt else "이미지 대체 텍스트가 있습니다." if "<img" in safe_html else "이미지가 없어 대체 텍스트 검사는 해당 없음입니다.")
    add("duplicate_content", "not_measured", "기존 공개 글 전체와의 중복 검사는 연결되어 있지 않습니다.")
    add("search_performance", "not_measured", "Search Console이 연결되지 않아 노출·클릭·CTR·순위는 측정되지 않았습니다.")
    add("fact_review", "ready" if metadata.fact_verified_at else "review",
        "사실 검증 시각이 기록되어 있습니다." if metadata.fact_verified_at else "사실 검증 시각을 확인하고 최신성을 검토하세요.")
    add("blogger_search_description", "review", "Blogger 관리자 글 편집에서 검색 설명을 확인해야 합니다. API v3 Posts 리소스에는 해당 필드가 문서화되어 있지 않습니다.")
    add("blogger_theme_seo", "review", "각 블로그 테마의 canonical, robots, Open Graph, 구조화 데이터, 사이트맵 출력을 직접 확인해야 합니다.")
    add("editorial_review", "ready" if metadata.editorial_status in {"editorial_review_passed", "approved"} else "review",
        "편집 검토 상태가 기록되어 있습니다." if metadata.editorial_status in {"editorial_review_passed", "approved"} else "사람 편집 검토가 완료되지 않았거나 상태가 확인되지 않았습니다.")
    return checks
