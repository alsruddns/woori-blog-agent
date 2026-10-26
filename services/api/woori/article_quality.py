"""Deterministic full-article checks; semantic accuracy remains human reviewed."""

import re
from typing import Any

from .ai import Draft
from .grounding import inspect


def _tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for segment in re.findall(
        r"[A-Za-z0-9]+|[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", value.casefold()
    ):
        if re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", segment):
            tokens.extend(segment[i : i + 2] for i in range(max(1, len(segment) - 1)))
        else:
            tokens.append(segment)
    return tokens


def longest_source_overlap(body: str, sources: list[dict[str, Any]]) -> int:
    """Largest consecutive word run copied verbatim from one source excerpt."""
    body_tokens = _tokens(body)
    longest = 0
    for source in sources:
        source_tokens = _tokens(str(source.get("evidence", "")))
        if not body_tokens or not source_tokens:
            continue
        # Bound the check while detecting short excerpt copying.
        for start in range(len(source_tokens)):
            matched = 0
            for body_start in range(len(body_tokens)):
                count = 0
                while (
                    start + count < len(source_tokens)
                    and body_start + count < len(body_tokens)
                    and source_tokens[start + count] == body_tokens[body_start + count]
                ):
                    count += 1
                    if count >= 30:
                        break
                matched = max(matched, count)
                if matched >= 30:
                    break
            longest = max(longest, matched)
            if longest >= 30:
                return longest
    return longest


def evaluate(
    draft: Draft, sources: list[dict[str, Any]], language: str, as_of: str, fact_count: int
) -> dict[str, Any]:
    grounded = inspect(draft, sources, language, as_of)
    headings = re.findall(r"(?m)^\s*#{2,3}\s+.+$", draft.body)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", draft.body) if len(_tokens(p)) >= 5]
    title_tokens = {token for token in _tokens(draft.title) if len(token) >= 2}
    body_tokens = set(_tokens(draft.body))
    keyword_tokens = {
        token for keyword in draft.keywords for token in _tokens(keyword) if len(token) >= 2
    }
    keyword_coverage = bool(keyword_tokens & (set(_tokens(draft.title)) | body_tokens))
    keyword_metadata_clean = len(draft.keywords) <= 6 and not any(
        re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{10}-\d{2}-\d{6}\b", keyword)
        for keyword in draft.keywords
    )
    source_text = " ".join(str(source.get("evidence", "")) for source in sources).casefold()
    legal_access_phrases = re.findall(
        r"\b(?:public record|publicly available|publicly accessible|free to (?:access|reuse)|copyright(?:ed)?)\b",
        (draft.title + "\n" + draft.body + "\n" + draft.summary).casefold(),
    )
    source_rights_claims_supported = all(phrase in source_text for phrase in legal_access_phrases)
    source_overlap = longest_source_overlap(draft.body, sources)
    user_text = "\n".join((draft.title, draft.summary, draft.body, *draft.keywords))
    user_text_without_citations = re.sub(r"\[source:[^\]]+\]", "", user_text)
    no_internal_ids = not re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        user_text_without_citations,
        re.IGNORECASE,
    )
    scripts = {
        "hangul": len(re.findall(r"[\uac00-\ud7af]", user_text)),
        "kana": len(re.findall(r"[\u3040-\u30ff]", user_text)),
        "cyrillic": len(re.findall(r"[\u0400-\u04ff]", user_text)),
        "arabic": len(re.findall(r"[\u0600-\u06ff]", user_text)),
    }
    forbidden_script = (
        scripts["cyrillic"] > 0 or scripts["arabic"] > 0
        or (language == "ko" and scripts["kana"] > 0)
        or (language.startswith("zh") and (scripts["hangul"] > 0 or scripts["kana"] > 0))
        or (language == "ja" and scripts["hangul"] > 0)
        or (language == "en" and any(scripts[key] > 0 for key in ("hangul", "kana")))
    )
    target_script_present = (
        scripts["hangul"] > 0 if language == "ko"
        else scripts["kana"] > 0 if language == "ja"
        else bool(re.search(r"[\u3400-\u9fff]", user_text)) if language.startswith("zh")
        else bool(re.search(r"[A-Za-z]", user_text)) if language == "en"
        else True
    )
    # Adapt length to available evidence. Narrow filing metadata is not padded
    # to a generic SEO word target; sections and support still have to be present.
    threshold = 3 if fact_count >= 4 else 2
    checks = {
        **grounded["rule_checks"],
        "article_structure": len(headings) >= threshold and len(paragraphs) >= threshold,
        "title_body_alignment": bool(title_tokens & body_tokens) if title_tokens else False,
        "keyword_search_intent_coverage": keyword_coverage,
        "keywords_are_search_terms_not_internal_ids": keyword_metadata_clean,
        "no_internal_ids_in_user_text": no_internal_ids,
        "keyword_list_is_bounded_and_unique": (
            1 <= len(draft.keywords) <= 6
            and len({" ".join(keyword.casefold().split()) for keyword in draft.keywords})
            == len(draft.keywords)
            and all(1 <= len(keyword.strip()) <= 80 for keyword in draft.keywords)
        ),
        "no_forbidden_foreign_script_mixing": not forbidden_script,
        "target_writing_system_present": target_script_present,
        "legal_access_claims_grounded_in_supplied_source": source_rights_claims_supported,
        "no_mass_direct_quote": source_overlap < 25,
    }
    return {
        "checks": checks,
        "machine_passed": all(checks.values()),
        "grounding_details": {
            key: grounded[key]
            for key in (
                "proper_name_candidates",
                "missing_proper_names",
                "unsupported_proper_names",
                "unexpected_numbers",
                "uncited_paragraphs",
                "invalid_source_urls",
            )
            if key in grounded
        },
        "human_review_required": True,
        "semantic_accuracy": "human_review_required",
        "naturalness": "human_review_required",
        "rights_review": "human_review_required",
        "publish_ready": False,
        "word_count": len(_tokens(draft.body)),
        "section_count": len(headings),
        "paragraph_count": len(paragraphs),
        "source_overlap_words_max": source_overlap,
        "fact_count": fact_count,
        "script_counts": scripts,
        "search_intent": "Summarize and explain the supplied official filing/release; not investment advice",
    }
