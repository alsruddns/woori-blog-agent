"""Free, explainable discovery heuristics, never semantic or publication approval."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import topics

VERSION = "editorial-selection/3"


class Weights(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    news_value: int = Field(25, ge=0, le=100)
    freshness: int = Field(20, ge=0, le=100)
    reader_relevance: int = Field(15, ge=0, le=100)
    interest: int = Field(15, ge=0, le=100)
    article_potential: int = Field(15, ge=0, le=100)
    analysis_value: int = Field(10, ge=0, le=100)

    @model_validator(mode="after")
    def total(self) -> Weights:
        if sum(self.model_dump().values()) != 100:
            raise ValueError("weights_must_total_100")
        return self


@lru_cache(maxsize=8192)
def normalize(query: str) -> str:
    # NFKC handles width and compatibility kana; dates and script stay intact.
    # Ambiguous transliterations, simplified/traditional characters and entity
    # aliases require explicit reviewed identity; never infer these equivalences.
    value = unicodedata.normalize("NFKC", query).casefold()
    return " ".join(
        "".join(" " if unicodedata.category(c).startswith("P") else c for c in value).split()
    )


def canonical_query(query: str, geo: str, aliases: list[dict[str, Any]]) -> str:
    value = normalize(query)
    # Only operator-reviewed, source-region scoped aliases. No automatic
    # transliteration, homograph or simplified/traditional semantic merging.
    mapping = {normalize(a["alias"]): normalize(a["canonical"]) for a in aliases if a["geo"] == geo}
    for alias in sorted(mapping, key=len, reverse=True):
        if value == alias:
            return mapping[alias]
        if value.startswith(alias + " "):
            return mapping[alias] + value[len(alias) :]
    return value


def overlap(query: str, title: str) -> bool:
    a, b = set(normalize(query).split()), set(normalize(title).split())
    # Date changes are a new-event signal, never erased during grouping.
    if set(re.findall(r"\d+", query)) != set(re.findall(r"\d+", title)):
        return False
    return len(a) >= 4 and len(b) >= 4 and len(a & b) / max(1, len(a | b)) >= 0.85


def score_candidate(
    row: dict[str, Any],
    peers: list[dict[str, Any]],
    weights: Weights,
    now: datetime,
    duplicate: list[dict[str, Any]],
) -> dict[str, Any]:
    query = row["representative_query"]
    key = normalize(query)
    news = (row.get("raw_payload") or {}).get("news_items") or []
    headlines = [normalize(str(x.get("title", ""))) for x in news if isinstance(x, dict)]
    terms = key.split()
    relevant = [h for h in headlines if key in h or (terms and all(t in h.split() for t in terms))]
    context = " ".join(relevant)
    domains = topics.research_domains(query + " " + context)
    started = row.get("trend_started_at")
    age = max(0, (now - started).total_seconds() / 3600) if started else None
    freshness = (
        100
        if age is not None and age <= 6
        else 75
        if age is not None and age <= 24
        else 30
        if age is not None and age <= 72
        else 0
    )
    volumes = sorted(
        {
            p["source_volume_lower_bound"]
            for p in peers
            if p.get("geo") == row.get("geo") and p.get("source_volume_lower_bound") is not None
        }
    )
    volume = row.get("source_volume_lower_bound")
    interest = round(100 * (volumes.index(volume) + 1) / len(volumes)) if volume in volumes else 0
    important = bool(
        set(domains)
        & {
            "economy",
            "finance",
            "policy",
            "technology",
            "artificial-intelligence",
            "semiconductors",
        }
    )
    components = {
        "news_value": 85 if important else 60 if domains else 25,
        "freshness": freshness,
        "reader_relevance": 75,
        "interest": interest,
        "article_potential": 75 if context else 45 if domains else 15,
        "analysis_value": 70 if important else 45 if domains else 15,
    }
    score = round(sum(components[k] * v for k, v in weights.model_dump().items()) / 100, 2)
    reasons = [
        "규칙 기반 조사 우선순위입니다. 뉴스 사실·독자 적합성은 조사와 편집 검토가 필요합니다.",
        "검색 관심도는 같은 국가의 현재 회차 하한값 순위만 비교했습니다.",
        "독자 관련성은 명시적으로 활성화한 Blogger 국가 매핑을 기준으로 합니다.",
    ]
    risk = any(
        term in key + " " + context
        for term in (
            "rumor",
            "루머",
            "열애설",
            "불륜",
            "death",
            "사망",
            "訃報",
            "死亡",
            "deceased",
            "died",
        )
    )
    if duplicate:
        decision = "duplicate"
        reasons.append(
            "동일 사건 또는 동일 정규화 검색어의 기존 작성 이력이 있습니다. 새 후속 사건은 명시적인 사건 구분이 필요합니다."
        )
    elif risk:
        decision = "high_risk"
        reasons.append("루머·사망 등 고위험 표현이 있어 사람 확인 전 자동 작성에서 보류합니다.")
    elif (
        not key
        or key in topics.BROAD_QUERIES
        or key in {"technology news", "latest news", "news", "뉴스", "最新ニュース", "最新消息"}
    ):
        decision = "low_value"
        reasons.append("너무 넓은 검색 의도로 기사 쟁점을 식별할 수 없습니다.")
    elif age is not None and age > 72:
        decision = "low_value"
        reasons.append("제공된 사건 시작 시각이 72시간보다 오래됐습니다.")
    elif not domains and not context:
        decision = "insufficient_context"
        reasons.append("사건 배경이 부족합니다. 출처 URL 부재만으로 폐기한 것은 아닙니다.")
    elif not domains or score < 60 or age is None:
        decision = "review_candidate"
        reasons.append("추가 독립 조사로 기사 가치를 확인할 후보입니다.")
    else:
        decision = "selected"
        reasons.append("최신성과 분야·조사 맥락이 있는 후보로 독립 웹 조사를 우선합니다.")
    return {
        "normalized_query": key,
        "score": score,
        "components": components,
        "decision": decision,
        "reasons": reasons,
        "duplicate_matches": duplicate,
        "category": domains[0] if domains else row.get("category"),
        "source_availability": "unverified",
        "semantic_event_identity": "unconfirmed",
        "age_hours": age,
        "engine_version": VERSION,
        "fact_verified": False,
    }
