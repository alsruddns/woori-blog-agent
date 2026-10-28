"""Conservative diagnostics, not semantic truth or fluency certification."""

import hashlib
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import langcodes

from .ai import Draft


def numbers(text: str) -> set[str]:
    months = {
        name.casefold(): index
        for index, name in enumerate(
            (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            1,
        )
    }
    dates: set[str] = set()

    month_pattern = r"\b(" + "|".join(months) + r")\s+(\d{1,2})(?:,\s*(\d{4}))?\b"
    # Written dates, including Taiwan Minguo years, are compared by date value.
    localized_pattern = (
        r"(?<!\d)(?:(\d{1,4})\s*(?:\u5e74|\ub144)\s*)?(\d{1,2})\s*(?:\u6708|\uc6d4)\s*(\d{1,2})\s*(?:\u65e5|\u53f7|\u865f|\uc77c)?"
    )

    def date_lists(sentence: str, pattern: str, kind: str) -> str:
        matches = list(re.finditer(pattern, sentence, flags=re.IGNORECASE))
        explicit_years = [
            int(m.group(3) if kind == "named" else m.group(1))
            for m in matches
            if (m.group(3) if kind == "named" else m.group(1))
        ]
        unique_years = set(explicit_years)
        replacements: list[tuple[int, int]] = []
        for match in matches:
            if kind == "named":
                month = months[match.group(1).casefold()]
                day = int(match.group(2))
                explicit = int(match.group(3)) if match.group(3) else None
                year = explicit or (next(iter(unique_years)) if len(unique_years) == 1 else None)
            else:
                explicit = int(match.group(1)) if match.group(1) else None
                month, day = int(match.group(2)), int(match.group(3))
                year = explicit or (next(iter(unique_years)) if len(unique_years) == 1 else None)
            if year and kind == "localized" and 1 <= year <= 1911:
                year += 1911
            if year:
                try:
                    normalized_date = date(year, month, day)
                except ValueError:
                    continue
                dates.add(f"DATE:{normalized_date.isoformat()}")
                replacements.append(match.span())
        for start, end in reversed(replacements):
            sentence = sentence[:start] + " " + sentence[end:]
        return sentence

    sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    normalized: list[str] = []
    for sentence in sentences:
        sentence = date_lists(sentence, month_pattern, "named")
        sentence = date_lists(sentence, localized_pattern, "localized")
        normalized.append(sentence)
    text = "\n".join(normalized)

    def numeric_date(match: re.Match[str]) -> str:
        value = match.group(1)
        if len(value) == 8 and value.isdigit():
            year, month, day = int(value[:4]), int(value[4:6]), int(value[6:])
        else:
            year, month, day = (int(x) for x in re.split(r"[-/.]", value))
        try:
            normalized_date = date(year, month, day)
        except ValueError:
            return value
        dates.add(f"DATE:{normalized_date.isoformat()}")
        return " "
        return value

    # ASCII boundaries keep localized particles (e.g. Korean 조사) outside the
    # date token while still recognizing the complete ISO date.
    text = re.sub(
        r"(?<![A-Za-z0-9])(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{8})(?![A-Za-z0-9])",
        numeric_date,
        text,
    )

    # Normalize Taiwan fiscal years and currency magnitudes before comparing a
    # source excerpt with localized prose. One 億 is NT$100 million; therefore
    # 6,076億元 and NT$607.6 billion are the same amount. Currency identity is
    # reviewed separately, and aliases remain unit-bound to preserve other numbers.
    # They remain unit-bound so unrelated factual numbers stay exact.
    normalized_values: set[str] = set(dates)

    def scaled_amount(match: re.Match[str], multiplier: Decimal) -> str:
        amount = Decimal(match.group(1).replace(",", "")) * multiplier
        normalized_values.add(f"MAGNITUDE:{amount.normalize():f}")
        return " "

    amount_patterns = (
        (r"(?i)(?:NT\$|TWD\s*)\s*([\d,]+(?:\.\d+)?)\s*(billion|bn)\b", Decimal(1000000000)),
        (r"(?i)(?:NT\$|TWD\s*)\s*([\d,]+(?:\.\d+)?)\s*(million|mn)\b", Decimal(1000000)),
        (r"(?i)(?:NT\$|TWD\s*)\s*([\d,]+(?:\.\d+)?)\s*(thousand|k)\b", Decimal(1000)),
    )
    for pattern, multiplier in amount_patterns:
        def replace_scaled_amount(
            match: re.Match[str], scale: Decimal = multiplier
        ) -> str:
            return scaled_amount(match, scale)

        text = re.sub(pattern, replace_scaled_amount, text)

    def hundred_million_amount(match: re.Match[str]) -> str:
        return scaled_amount(match, Decimal(100000000))

    text = re.sub(
        r"(?<!\d)([\d,]+(?:\.\d+)?)\s*(?:\u5104|\uc5b5)\s*(?:\u5143)?(?:\s*\ub300\ub9cc\ub2ec\ub7ec)?",
        hundred_million_amount,
        text,
    )

    def base_twd_amount(match: re.Match[str]) -> str:
        return scaled_amount(match, Decimal(1))

    text = re.sub(
        r"(?i)(?:NT\$|TWD\s*)\s*([\d,]+)(?![\d,.])",
        base_twd_amount,
        text,
    )

    text = re.sub(
        r"(?<!\d)([\d,]+)\s*(?:\u65b0\u53f0\u5e63|\u53f0\u5e63|\u5143|\ub300\ub9cc\ub2ec\ub7ec)",
        base_twd_amount,
        text,
    )

    def fiscal_year(match: re.Match[str]) -> str:
        year = int(match.group(1))
        gregorian = year + 1911 if year <= 1911 else year
        normalized_values.add(f"YEAR:{gregorian}")
        return " "

    text = re.sub(r"(?<!\d)(1\d{2,3})\s*\u5e74\u5ea6", fiscal_year, text)
    text = re.sub(r"(?i)\b(?:fiscal(?:\s+year)?|FY)\s*(20\d{2})\b", fiscal_year, text)
    text = re.sub(r"(?<!\d)(20\d{2})\s*\ub144\ub3c4", fiscal_year, text)

    text = re.sub(
        r"https?://\S+|\[source:[^\]]+\]|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b",
        "",
        text,
    )
    # Section labels such as `## 1` are structure, not factual numerals. Keep
    # stripping numbered-list prefixes as well, without hiding inline numbers.
    text = re.sub(r"(?m)^\s*#{1,6}\s+\d+\s*$", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s*)?\d+[.)]\s", "", text)
    numeric_tokens = re.findall(r"\d+(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", text)
    return normalized_values | {
        str(float(n.replace(",", ""))) for n in numeric_tokens if len(n) < 20
    }


_NON_NAME_STARTS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "announced",
    "by",
    "for",
    "from",
    "in",
    "on",
    "the",
    "terminated",
    "to",
    "these",
    "this",
}

_NON_NAME_ENDS = {
    "announced",
    "announcement",
    "announces",
    "actions",
    "analysis",
    "briefing",
    "concludes",
    "conclusion",
    "explained",
    "filed",
    "guide",
    "highlights",
    "overview",
    "report",
    "review",
    "summary",
    "terminated",
    "termination",
    "update",
}

_GENERIC_HEADLINE_NAMES = {
    "enforcement actions",
    "regulatory measures",
    "official announcement",
    "board's discount rate meetings",
    "q filing",
}

_EVIDENCE_TERM_ALIASES = {
    "united states dollar": re.compile(
        r"\bUSD\b|\bU\.?S\.? dollars?\b|\bUnited States dollars?\b", re.IGNORECASE
    ),
}


def proper_names(text: str) -> set[str]:
    """Conservative multi-token Latin names for exact-preservation checks."""
    # Unicode ``\b`` treats Hangul as a word character, so an unchanged
    # Latin proper name followed by a Korean particle was missed. Bound
    # against ASCII name characters while preserving exact name matching.
    pattern = (
        r"(?<![A-Za-z0-9-])[A-Z][A-Za-z0-9&'\-]*"
        r"(?:\s+[A-Z][A-Za-z0-9&'\-]*){1,3}(?![A-Za-z0-9])"
    )
    names: set[str] = set()
    for candidate in re.findall(pattern, text):
        tokens = candidate.split()
        while tokens and tokens[0].casefold() in _NON_NAME_STARTS:
            tokens.pop(0)
        while tokens and tokens[-1].casefold().strip(".,:;!?()") in _NON_NAME_ENDS:
            tokens.pop()
        name = " ".join(tokens)
        if (
            len(tokens) >= 2
            and name.casefold() not in _GENERIC_HEADLINE_NAMES
            and any(len(token.strip(".,'&")) > 2 for token in tokens)
        ):
            names.add(name)
    return names


def repeated_paragraphs(text: str) -> list[str]:
    text = prose_without_headings(text)
    paragraphs = [" ".join(p.casefold().split()) for p in re.split(r"\n\s*\n", text)]
    substantive = [p for p in paragraphs if len(re.findall(r"\w+", p)) >= 8]
    return sorted({p for p in substantive if substantive.count(p) > 1})


def repeated_sentences(text: str) -> list[str]:
    text = prose_without_headings(text)
    text = re.sub(r"\[source:[^\]]+\]|https?://\S+", "", text)
    sentences = [" ".join(s.casefold().split()) for s in re.split(r"(?<=[.!?。！？])\s+|\n+", text)]
    substantive = [s for s in sentences if len(re.findall(r"\w+", s)) >= 6]
    return sorted({s for s in substantive if substantive.count(s) > 1})


def prose_without_headings(text: str) -> str:
    """Remove actual Markdown headings, while retaining cited text on heading lines."""
    return re.sub(r"(?m)^\s*#{1,6}\s+(?!.*\[source:[^\]]+\]).*$", "", text)


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


def _evidence_supported_term_alias(name: str, evidence: str) -> bool:
    pattern = _EVIDENCE_TERM_ALIASES.get(name.casefold().rstrip("s"))
    return bool(pattern and pattern.search(evidence))


def inspect(
    draft: Draft, sources: list[dict[str, Any]], language: str, as_of: str
) -> dict[str, Any]:
    allowed_ids = {str(s["id"]) for s in sources}
    allowed_urls = {s["url"].rstrip("/") for s in sources}
    body = draft.title + "\n" + draft.body + "\n" + draft.summary
    prose_body = prose_without_headings(draft.body)
    found_urls = {u.rstrip("/.,);]") for u in re.findall(r"https?://[^\s<>]+", body)}
    evidence = "\n".join(str(s["evidence"]) + " " + str(s.get("published_at", "")) for s in sources)
    unexpected_numbers = sorted(numbers(body) - numbers(evidence + " " + as_of))
    evidence_names = proper_names(evidence)
    output_names = proper_names(draft.title + "\n" + prose_body + "\n" + draft.summary)
    missing_names = sorted(evidence_names - output_names)
    # A shorter exact phrase such as "Federal Reserve" is supported by the
    # source's full name "Federal Reserve Board"; added entity tokens still fail.
    ungrounded_names = sorted(
        name
        for name in output_names - evidence_names
        if not any(re.sub(r"'s$", "", name) in evidence_name for evidence_name in evidence_names)
        and not _evidence_supported_term_alias(name, evidence)
    )
    cited_ids = set(re.findall(r"\[source:([^\]]+)\]", draft.body))
    substantive_paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", prose_body) if len(re.findall(r"\w+", p)) >= 8
    ]
    uncited_paragraphs = [
        p[:120] for p in substantive_paragraphs if not re.search(r"\[source:[^\]]+\]", p)
    ]
    invalid_source_urls = sorted(
        str(s.get("url", ""))
        for s in sources
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
