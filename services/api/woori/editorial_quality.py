"""Version-bound editorial diagnostics. No claim, rights, or publish gates are promoted."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

VERSION = "trendjournal-quality/3.1"
WEIGHTS = {
    "caution": 20,
    "substance": 20,
    "analysis": 20,
    "seo": 15,
    "readability": 10,
    "localization": 10,
    "structure": 5,
}


def evaluate(version: dict[str, Any], imported: dict[str, Any]) -> dict[str, Any]:
    title, body = version["title"], version["body_markdown"]
    seo = version.get("seo_metadata") or {}
    description = str(seo.get("search_description") or "")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    headings = re.findall(r"(?m)^#{2,3}\s+.+", body)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s*", body) if len(s.strip()) > 15]
    duplicates = [s for s, n in Counter(sentences).items() if n > 1]
    deck_blocks = list(paragraphs)
    if deck_blocks and re.match(r"^#\s+", deck_blocks[0]):
        deck_blocks.pop(0)
    explicit_deck = bool(
        deck_blocks
        and re.fullmatch(
            r"#{1,3}\s*(?:summary(?: deck)?|요약|概要|要点|摘要|导语)",
            deck_blocks[0],
            re.IGNORECASE,
        )
    )
    if explicit_deck:
        deck_blocks.pop(0)
    deck = bool(
        deck_blocks
        and len(deck_blocks[0]) >= 20
        and not deck_blocks[0].startswith(
            ("#", "<", "[source:") if explicit_deck else ("#", "<", "- ", "[source:")
        )
    )
    internal = re.findall(
        r"(?im)^.*(?:TODO|FIXME|FACT-F\d+|publish_ready|generation_ready|편집 메모|編集メモ).*$",
        body,
    )
    # Import bodies are Markdown; raw tags (including unbalanced harmless tags)
    # must be edited through the existing server HTML renderer, never trusted.
    unsafe = bool(
        re.search(
            r"<\s*/?\s*[a-z][\w-]*(?:\s[^>]*|/?)>|\bon\w+\s*=|javascript:", body, re.IGNORECASE
        )
    )
    long_paragraphs = [(i, p) for i, p in enumerate(paragraphs) if len(p) > 600]
    checks = {
        "title_length": 5 <= len(title) <= 100,
        "meta_description": 0 < len(description) <= 150,
        "body_length": len(body) >= 300,
        "summary_deck": deck,
        "subheadings": len(headings) >= 2,
        "paragraph_length": not long_paragraphs,
        "duplicate_sentences": not duplicates,
        "internal_notes": not internal,
        "safe_html": not unsafe,
        "labels": len(version.get("blogger_labels") or []) <= 8,
    }
    terms = seo.get("primary_terms") or []
    stuffing = [
        term
        for term in terms
        if term and body.casefold().count(str(term).casefold()) > max(6, len(body) // 150)
    ]
    checks["keyword_repetition"] = not stuffing
    scores: dict[str, int | None] = {k: None for k in WEIGHTS}
    # Only measured static dimensions receive scores. Completeness, reasoning,
    # caution and naturalness need semantic review, not fabricated default scores.
    for dimension, keys in {
        "seo": ["title_length", "meta_description", "subheadings", "labels", "keyword_repetition"],
        "readability": ["paragraph_length", "duplicate_sentences"],
        "structure": ["summary_deck", "subheadings", "internal_notes", "safe_html"],
    }.items():
        scores[dimension] = round(100 * sum(checks[k] for k in keys) / len(keys))
    suggestions: list[dict[str, Any]] = []

    def add(
        kind: str,
        field: str,
        original: str,
        reason: str,
        proposal: str | None = None,
        location: str = "document",
    ) -> None:
        suggestions.append(
            {
                "id": f"s{len(suggestions) + 1}",
                "category": kind,
                "field": field,
                "location": location,
                "original": original,
                "proposal": proposal,
                "reason": reason,
                "expected_effect": reason,
                "automatic": proposal is not None,
                "fact_check_required": proposal is None,
            }
        )

    if not checks["title_length"]:
        add("seo", "title", title, "제목을 5~100자 범위에서 검색 의도가 드러나게 편집하세요.")
    if not checks["meta_description"]:
        add(
            "seo",
            "search_description",
            description,
            "검색 설명을 실제 원고 내용으로 150자 이내에 직접 작성하세요.",
        )
    if not deck:
        add(
            "structure",
            "body_markdown",
            paragraphs[0] if paragraphs else "",
            "제목 바로 아래에 핵심 내용과 독자 영향을 요약하는 Summary Deck을 작성하세요.",
        )
    if not checks["body_length"]:
        add(
            "substance",
            "body_markdown",
            body,
            "배경과 핵심 쟁점이 충분한지 확인하세요. 근거 없이 분량을 늘리지 마세요.",
        )
    if len(headings) < 2:
        add(
            "structure",
            "body_markdown",
            body[:300],
            "쟁점과 분석을 구분하는 논리적인 소제목을 확인하세요.",
        )
    for sentence in duplicates[:20]:
        # Keep first occurrence. Apply uses a bounded exact operation.
        add(
            "readability",
            "duplicate_sentence",
            sentence,
            "같은 문장의 반복을 줄여 모바일 가독성을 개선합니다.",
            sentence,
        )
    for i, paragraph in long_paragraphs[:20]:
        add(
            "readability",
            "body_markdown",
            paragraph,
            "600자를 넘는 문단을 논리 단위로 나누세요.",
            location=f"paragraph:{i + 1}",
        )
    for note in internal[:20]:
        add("structure", "body_markdown", note, "독자에게 노출된 내부 메모를 검토하고 제거하세요.")
    if unsafe:
        add(
            "structure",
            "body_markdown",
            body[:300],
            "허용되지 않는 HTML 또는 실행 가능한 속성을 제거하세요.",
        )
    for term in stuffing:
        add(
            "seo",
            "body_markdown",
            str(term),
            "핵심 검색어 반복이 과도합니다. 의미를 유지하며 표현을 편집하세요.",
        )
    risky = re.findall(
        r"[^\n.!?。！？]*(?:guaranteed|certainly|확정됐다|반드시|絶対|必ず|保证|必然)[^\n.!?。！？]*",
        title + "\n" + body,
        re.IGNORECASE,
    )
    for sentence in risky[:15]:
        add(
            "caution",
            "review",
            sentence,
            "단정·예측 표현의 출처와 확정 상태를 확인하세요. 규칙 탐지는 사실 오류 판정이 아닙니다.",
        )
    claims = imported.get("claims") or []
    # Imported self-reported span statuses never establish independent verification.
    return {
        "stage": "static",
        "scores": scores,
        "overall_score": None,
        "measured_score": round(
            sum(v * WEIGHTS[k] for k, v in scores.items() if v is not None)
            / sum(WEIGHTS[k] for k in scores if scores[k] is not None),
            2,
        ),
        "measured_weight": sum(WEIGHTS[k] for k in scores if scores[k] is not None),
        "checks": checks,
        "suggestions": suggestions,
        "risky_expressions": risky,
        "evidence": {
            "verified_claims": None,
            "unverified_claims": len(claims),
            "source_count": len(imported.get("sources") or []),
            "source_original_examined": False,
            "verification_basis": "independent_claim_review_not_performed",
        },
        "human_review_required": True,
        "semantic_review": "not_run",
        "localization_language": imported["language_code"],
        "publish_ready": False,
        "fact_verified": False,
        "engine_version": VERSION,
    }


def apply_suggestions(
    version: dict[str, Any],
    suggestions: list[dict[str, Any]],
    ids: list[str],
    manual_review_confirmed: bool = False,
) -> dict[str, Any]:
    updated = dict(version)
    found = {s["id"]: s for s in suggestions}
    if not ids or len(set(ids)) != len(ids) or any(i not in found for i in ids):
        raise ValueError("unknown_or_duplicate_suggestion")
    for key in ids:
        suggestion = found[key]
        if not suggestion["automatic"] and not manual_review_confirmed:
            raise ValueError("suggestion_requires_manual_edit_and_fact_review")
        if suggestion["field"] != "duplicate_sentence":
            field = suggestion["field"]
            if field not in {"title", "body_markdown", "search_description"} or not suggestion.get(
                "proposal"
            ):
                raise ValueError("unsupported_automatic_edit")
            original, proposal = suggestion["original"], suggestion["proposal"]
            if field == "search_description":
                seo = dict(updated["seo_metadata"])
                if seo.get(field, "").count(original) != 1:
                    raise ValueError("suggestion_no_longer_matches")
                seo[field] = seo[field].replace(original, proposal, 1)
                updated["seo_metadata"] = seo
            else:
                if updated[field].count(original) != 1:
                    raise ValueError("suggestion_no_longer_matches")
                updated[field] = updated[field].replace(original, proposal, 1)
            continue
        sentence = suggestion["original"]
        body = updated["body_markdown"]
        # Match complete sentence tokens, never remove a substring of another claim.
        occurrences = [m for m in re.finditer(re.escape(sentence), body)]
        if len(occurrences) < 2:
            raise ValueError("suggestion_no_longer_matches")
        for match in reversed(occurrences[1:]):
            body = body[: match.start()] + body[match.end() :]
        updated["body_markdown"] = body
    return updated
