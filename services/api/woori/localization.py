"""Evidence-first multilingual rendering. Machine checks never certify meaning."""

import hashlib
import re
import time
from collections.abc import Callable
from typing import Any

import langcodes

from .article_quality import longest_source_overlap
from .grounding import numbers, proper_names, repeated_sentences

EXTRACTOR_VERSION = "fact-ledger-v1"


def fact_ledger(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Split only reviewed source spans; IDs are stable for this exact span and source."""
    facts: list[dict[str, Any]] = []
    source_id = str(source["id"])
    language = str(source.get("source_language") or "und")
    if language != "und" and not langcodes.tag_is_valid(language):
        raise ValueError("invalid_source_language")
    chunks = re.split(r"(?<=[.!?])\s+|\n+", str(source.get("evidence", "")))
    for chunk in chunks:
        excerpt = " ".join(chunk.split()).strip()
        if not excerpt:
            continue
        digest = hashlib.sha256(f"{source_id}\0{language}\0{excerpt}".encode()).hexdigest()[:20]
        entities = sorted(proper_names(excerpt))
        facts.append({
            "fact_key": digest,
            "source_id": source_id,
            "source_language": language,
            "source_excerpt": excerpt,
            "entity_ids": [hashlib.sha256(x.casefold().encode("utf-8")).hexdigest()[:20] for x in entities],
            "entities": entities,
            "numeric_values": sorted(numbers(excerpt)),
            "date_values": sorted(x for x in numbers(excerpt) if x.startswith("DATE:")),
            "citation_ids": [source_id],
            "verification_status": "source_span_verified",
            "extractor_version": EXTRACTOR_VERSION,
        })
    return facts


def _script_fraction(text: str, language: str) -> float:
    script = langcodes.Language.get(language).maximize().script or ""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    if script == "Kore":
        matched = sum("\uac00" <= c <= "\ud7a3" for c in letters)
    elif script == "Jpan":
        matched = sum("\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff" for c in letters)
    elif script in {"Hans", "Hant"}:
        matched = sum("\u3400" <= c <= "\u9fff" for c in letters)
    elif script == "Latn":
        matched = sum(c.isascii() for c in letters)
    else:
        matched = 0
    return matched / len(letters)


def localize_fact(
    fact: dict[str, Any], target_language: str,
    translator: Callable[[str, str, list[dict[str, Any]], list[str]], str] | None = None,
    glossary: list[dict[str, Any]] | None = None,
    force_local: bool = False,
) -> dict[str, Any]:
    """Translate only the excerpt. If no local adapter is supplied, fail closed."""
    if not langcodes.tag_is_valid(target_language):
        raise ValueError("invalid_target_language")
    glossary = glossary or []
    approved = [g for g in glossary if g.get("approved") and g.get("official_translation")
                and g.get("translation_source") and g.get("target_language") == target_language
                and g.get("source_language") == fact["source_language"]]
    started = time.monotonic()
    if fact["source_language"] == target_language and not force_local:
        localized = fact["source_excerpt"]
        calls = 0
    elif translator is None:
        return {
            "text": fact["source_excerpt"], "source_language": fact["source_language"],
            "target_language": target_language, "status": "held_translation_unavailable",
            "fact_id": str(fact["fact_key"]),
            "source_ids": [str(x) for x in fact.get("citation_ids", [])],
            "ai_calls": 0, "elapsed_ms": round((time.monotonic() - started) * 1000),
            "checks": {"language_matches": False, "numbers_preserved": True,
                       "entities_preserved": True, "citation_linked": bool(fact.get("citation_ids")),
                       "unapproved_terms_used": False},
            "human_review_required": True, "publish_ready": False,
        }
    else:
        localized = translator(fact["source_excerpt"], target_language, approved, fact.get("entities", []))
        calls = 1
    # Approved mappings are deterministic; unapproved entries are never injected as facts.
    for entry in approved:
        localized = re.sub(re.escape(entry["source_term"]), entry["localized_term"], localized, flags=re.IGNORECASE)
    source_numbers = set(fact["numeric_values"])
    target_numbers = numbers(localized)
    required_entities = set(fact.get("entities", []))
    glossary_sources = {str(g["source_term"]).casefold() for g in approved}
    localized_folded = localized.casefold()
    unapproved_terms_used = any(
        not entry.get("approved") and str(entry.get("localized_term", "")).casefold() in localized_folded
        for entry in glossary
        if entry.get("target_language") == target_language and entry.get("localized_term")
    )
    missing_entities = sorted(e for e in required_entities
                              if e.casefold() not in localized_folded and e.casefold() not in glossary_sources)
    # No new numerals/dates; source references are added outside model output.
    no_new_numbers = target_numbers.issubset(source_numbers)
    found_urls = {u.rstrip("/.,);]") for u in re.findall(r"https?://[^\s<>]+", localized)}
    allowed_urls = {str(fact.get("source_url", "")).rstrip("/")} - {""}
    no_added_urls = found_urls.issubset(allowed_urls)
    approved_targets = {str(g["localized_term"]).casefold() for g in approved}
    unexpected_entities = sorted(
        e for e in proper_names(localized)
        if not any(e.casefold() in n.casefold() for n in required_entities)
        and e.casefold() not in approved_targets
    )
    fraction = _script_fraction(localized, target_language)
    threshold = 0.06 if langcodes.Language.get(target_language).maximize().script == "Jpan" else 0.12
    language_ok = fraction > threshold
    source_overlap = longest_source_overlap(
        localized, [{"evidence": str(fact.get("source_excerpt", ""))}]
    )
    checks = {
        "language_matches": language_ok,
        "numbers_preserved": source_numbers.issubset(target_numbers) and no_new_numbers,
        "entities_preserved": not missing_entities,
        "no_unverified_entity_added": not unexpected_entities,
        "citation_linked": bool(fact.get("citation_ids")),
        "no_added_urls": no_added_urls,
        "no_unapproved_translation_asserted": not unapproved_terms_used,
        "no_repeated_sentences": not repeated_sentences(localized),
        "no_mass_direct_quote": source_overlap < 25,
    }
    return {
        "text": localized, "source_language": fact["source_language"],
        "target_language": target_language, "source_ids": [str(x) for x in fact.get("citation_ids", [])],
        "fact_id": fact["fact_key"], "status": "machine_passed" if all(checks.values()) else "quality_held",
        "checks": checks, "script_fraction": round(fraction, 3), "ai_calls": calls,
        "missing_entities": missing_entities,
        "unverified_entities": unexpected_entities,
        "longest_source_overlap_words": source_overlap,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "human_review_required": True, "semantic_accuracy": "human_review_required",
        "naturalness": "human_review_required", "publish_ready": False,
    }
