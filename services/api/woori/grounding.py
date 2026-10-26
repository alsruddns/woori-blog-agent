"""Conservative diagnostics, not semantic truth or fluency certification."""

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import langcodes

from .ai import Draft


def numbers(text: str) -> set[str]:
    months = {
        name.casefold(): index
        for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
            1,
        )
    }
    dates: set[str] = set()

    def named_date(match: re.Match[str]) -> str:
        month, day, year = match.group(1).casefold(), int(match.group(2)), int(match.group(3))
        dates.add(f"DATE:{year:04d}-{months[month]:02d}-{day:02d}")
        return " "

    text = re.sub(
        r"\b(" + "|".join(months) + r")\s+(\d{1,2}),?\s+(\d{4})\b",
        named_date,
        text,
        flags=re.IGNORECASE,
    )

    def numeric_date(match: re.Match[str]) -> str:
        value = match.group(1)
        if len(value) == 8 and value.isdigit():
            year, month, day = int(value[:4]), int(value[4:6]), int(value[6:])
        else:
            year, month, day = (int(x) for x in re.split(r"[-/.]", value))
        if 1 <= month <= 12 and 1 <= day <= 31:
            dates.add(f"DATE:{year:04d}-{month:02d}-{day:02d}")
            return " "
        return value

    text = re.sub(r"\b(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{8})\b", numeric_date, text)
    text = re.sub(r"https?://\S+|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "", text)
    text = re.sub(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s", "", text)
    return dates | {
        str(float(n.replace(",", ""))) for n in re.findall(r"\d+(?:[,\.]\d+)?", text) if len(n) < 20
    }


_NON_NAME_STARTS = {
    "a", "an", "and", "as", "at", "announced", "by", "for", "from", "in", "on",
    "the", "terminated", "to", "these", "this",
}


def proper_names(text: str) -> set[str]:
    """Conservative multi-token Latin names for exact-preservation checks."""
    pattern = r"\b[A-Z][A-Za-z0-9&'’\-]*(?:\s+[A-Z][A-Za-z0-9&'’\-]*){1,3}\b"
    names: set[str] = set()
    for candidate in re.findall(pattern, text):
        tokens = candidate.split()
        while tokens and tokens[0].casefold() in _NON_NAME_STARTS:
            tokens.pop(0)
        name = " ".join(tokens)
        if len(tokens) >= 2 and any(len(token.strip(".,'&")) > 2 for token in tokens):
            names.add(name)
    return names


def repeated_paragraphs(text: str) -> list[str]:
    text = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", text)
    paragraphs = [" ".join(p.casefold().split()) for p in re.split(r"\n\s*\n", text)]
    substantive = [p for p in paragraphs if len(re.findall(r"\w+", p)) >= 8]
    return sorted({p for p in substantive if substantive.count(p) > 1})


def repeated_sentences(text: str) -> list[str]:
    text = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", text)
    sentences = [" ".join(s.casefold().split()) for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text)]
    substantive = [s for s in sentences if len(re.findall(r"\w+", s)) >= 6]
    return sorted({s for s in substantive if substantive.count(s) > 1})


def extract_facts(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Split reviewed source text into traceable evidence units; do not infer truth."""
    facts: list[dict[str, str]] = []
    for source in sources:
        for index, sentence in enumerate(
            re.split(r"(?<=[.!?])\s+|\n+", str(source.get("evidence", ""))), start=1
        ):
            text = " ".join(sentence.split()).strip()
            if text:
                source_id = str(source["id"])
                fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
                facts.append(
                    {
                        "fact_id": f"{source_id}:{index}:{fingerprint}",
                        "text": text,
                        "source_id": source_id,
                    }
                )
    return facts


def inspect(
    draft: Draft, sources: list[dict[str, Any]], language: str, as_of: str
) -> dict[str, Any]:
    allowed_ids = {str(s["id"]) for s in sources}
    allowed_urls = {s["url"].rstrip("/") for s in sources}
    body = draft.title + "\n" + draft.body + "\n" + draft.summary
    prose_body = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", draft.body)
    found_urls = {u.rstrip("/.,);]") for u in re.findall(r"https?://[^\s<>]+", body)}
    evidence = "\n".join(str(s["evidence"]) + " " + str(s.get("published_at", "")) for s in sources)
    unexpected_numbers = sorted(numbers(body) - numbers(evidence + " " + as_of))
    evidence_names = proper_names(evidence)
    output_names = proper_names(draft.title + "\n" + prose_body + "\n" + draft.summary)
    missing_names = sorted(evidence_names - output_names)
    ungrounded_names = sorted(output_names - evidence_names)
    cited_ids = set(re.findall(r"\[source:([^\]]+)\]", draft.body))
    substantive_paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", prose_body)
        if len(re.findall(r"\w+", p)) >= 8
    ]
    uncited_paragraphs = [p[:120] for p in substantive_paragraphs if not re.search(r"\[source:[^\]]+\]", p)]
    invalid_source_urls = sorted(
        str(s.get("url", "")) for s in sources
        if urlparse(str(s.get("url", ""))).scheme != "https"
        or not urlparse(str(s.get("url", ""))).hostname
        or urlparse(str(s.get("url", ""))).username is not None
    )
    script = langcodes.Language.get(language).maximize().script

    def fraction(value: str) -> float:
        letters = [c for c in value if c.isalpha()]
        if script == "Kore":
            count = sum("\uac00" <= c <= "\ud7a3" for c in letters)
        elif script == "Jpan":
            count = sum("\u3040" <= c <= "\u30ff" for c in letters)
        elif script in ("Hans", "Hant", "Hani"):
            count = sum("\u4e00" <= c <= "\u9fff" for c in letters)
        elif script == "Latn":
            count = sum(c.isascii() for c in letters)
        else:
            count = 0
        return count / max(1, len(letters))

    script_fraction = fraction(draft.body)
    language_fields = {
        key: fraction(value) > (0.06 if script == "Jpan" else 0.12)
        for key, value in {
            "title": draft.title,
            "body": draft.body,
            "summary": draft.summary,
            "keywords": " ".join(draft.keywords),
        }.items()
    }
    checks = {
        "source_ids_valid": bool(draft.source_ids) and set(draft.source_ids).issubset(allowed_ids),
        "no_fabricated_urls": found_urls.issubset(allowed_urls),
        "source_urls_well_formed": not invalid_source_urls,
        "citation_ids_valid": cited_ids.issubset(allowed_ids),
        "factual_paragraphs_cited": bool(substantive_paragraphs) and not uncited_paragraphs,
        "no_unverified_numbers": not unexpected_numbers,
        "proper_names_preserved": not missing_names,
        "no_unsupported_proper_names": not ungrounded_names,
        "no_repeated_paragraphs": not repeated_paragraphs(draft.body),
        "no_repeated_sentences": not repeated_sentences(draft.body),
        "rights_recorded": all(bool(s.get("rights")) for s in sources),
        "current_sources": all(
            datetime.fromisoformat(str(s["valid_until"])) > datetime.now(UTC)
            for s in sources
            if s.get("valid_until")
        ),
        "language_script_present": script_fraction > (0.06 if script == "Jpan" else 0.12),
        "language_metadata_matches": all(language_fields.values()),
        "no_obvious_high_risk_claims": not any(
            term in body.casefold()
            for term in (
                "guaranteed profit",
                "guaranteed cure",
                "100% safe",
                "cures cancer",
                "i personally visited",
                "수익 보장",
                "완치 보장",
                "직접 방문",
            )
        ),
    }
    return {
        "rule_checks": checks,
        "unexpected_numbers": unexpected_numbers,
        "proper_name_candidates": sorted(evidence_names),
        "missing_proper_names": missing_names,
        "unsupported_proper_names": ungrounded_names,
        "uncited_paragraphs": uncited_paragraphs,
        "repeated_paragraphs": repeated_paragraphs(draft.body),
        "repeated_sentences": repeated_sentences(draft.body),
        "invalid_source_urls": invalid_source_urls,
        "source_url_network_existence": "not_rechecked_by_quality_gate",
        "script_fraction": round(script_fraction, 3),
        "language_fields": language_fields,
        "rule_pass": all(checks.values()),
        "semantic_fact_verification": "human_review_required",
        "naturalness": "human_review_required",
        "model_self_score_used_for_approval": False,
        "publish_ready": False,
    }
