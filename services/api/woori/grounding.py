"""Conservative diagnostics, not semantic truth or fluency certification."""

import re
from datetime import UTC, datetime
from typing import Any

import langcodes

from .ai import Draft


def numbers(text: str) -> set[str]:
    for index, month in enumerate(
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
    ):
        text = re.sub(month, str(index), text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "", text)
    text = re.sub(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s", "", text)
    return {
        str(float(n.replace(",", ""))) for n in re.findall(r"\d+(?:[,\.]\d+)?", text) if len(n) < 20
    }


def inspect(
    draft: Draft, sources: list[dict[str, Any]], language: str, as_of: str
) -> dict[str, Any]:
    allowed_ids = {str(s["id"]) for s in sources}
    allowed_urls = {s["url"].rstrip("/") for s in sources}
    body = draft.title + "\n" + draft.body + "\n" + draft.summary
    found_urls = {u.rstrip("/.,);]") for u in re.findall(r"https?://[^\s<>]+", body)}
    evidence = "\n".join(str(s["evidence"]) + " " + str(s.get("published_at", "")) for s in sources)
    unexpected_numbers = sorted(numbers(body) - numbers(evidence + " " + as_of))
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
        "no_unverified_numbers": not unexpected_numbers,
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
        "script_fraction": round(script_fraction, 3),
        "language_fields": language_fields,
        "rule_pass": all(checks.values()),
        "semantic_fact_verification": "human_review_required",
        "naturalness": "human_review_required",
        "model_self_score_used_for_approval": False,
        "publish_ready": False,
    }
