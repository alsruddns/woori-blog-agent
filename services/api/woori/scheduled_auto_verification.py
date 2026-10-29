"""Fail-closed, evidence-bound checks for scheduled manuscript publication.

This module does not create human review or publication approval. It only
evaluates source retrieval and reuse evidence produced by a reviewed collector.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NUMBER = re.compile(r"(?<!\w)[+-]?\d[\d,.]*(?:%|bp)?", re.IGNORECASE)
_NUMBER_VALUE = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_GBP_EN = re.compile(
    rf"£\s*({_NUMBER_VALUE})\s*(trillion|billion|million|thousand|tn|bn|m|k)?\b",
    re.IGNORECASE,
)
_GBP_KO = re.compile(
    rf"(?:(?P<trillion>{_NUMBER_VALUE})\s*조\s*)?"
    rf"(?:(?P<billion>{_NUMBER_VALUE})\s*억\s*)?"
    rf"(?:(?P<ten_thousand>{_NUMBER_VALUE})\s*만\s*)?파운드"
)
_PERCENT_POINTS = re.compile(
    rf"({_NUMBER_VALUE})\s*(?:%\s*포인트|퍼센트\s*포인트|percentage\s+points?)",
    re.IGNORECASE,
)
_PERCENT = re.compile(rf"({_NUMBER_VALUE})\s*(?:%|percent\b)", re.IGNORECASE)
_KO_MONTH_RANGE = re.compile(r"(20\d{2})년\s*(1[0-2]|0?[1-9])\s*~\s*(1[0-2]|0?[1-9])월")
_KO_YEAR_MONTH = re.compile(r"(20\d{2})년\s*(1[0-2]|0?[1-9])월")
_KO_BARE_MONTH_RANGE = re.compile(
    r"(?:(?P<year>20\d{2})\s*년\s*)?"
    r"(?P<start>1[0-2]|0?[1-9])\s*월?\s*(?:~|부터)\s*"
    r"(?P<end>1[0-2]|0?[1-9])\s*월(?:까지)?"
)
_KO_MONTH = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*월")
_EN_MONTH = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
_YEAR_OFFSET_EN = re.compile(r"\b(?:a|one)\s+year\s+(?:ago|earlier)\b", re.IGNORECASE)
_YEAR_OFFSET_KO = re.compile(r"(?<!\d)1\s*년\s*(?:전|앞서)")
_EN_MONTH_RANGE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s*-\s*to\s*-\s*(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
_EN_YEAR_MONTH = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_EN_MONTHS = {
    name.casefold(): number for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
        start=1,
    )
}


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return Decimal("NaN")


def _quantity_facts(text: str) -> set[tuple[str, str]]:
    """Normalize numeric facts across English and Korean number-unit notation.

    Currency units, percentages, percentage points, year-month references and
    ordinary counts remain distinct. This checks quantities and units only; it
    does not establish that a claim semantically follows from its source.
    """
    facts: set[tuple[str, str]] = set()
    consumed: list[tuple[int, int]] = []

    def remember(match: re.Match[str], kind: str, value: Decimal) -> None:
        if value.is_finite():
            facts.add((kind, format(value.normalize(), "f")))
        consumed.append(match.span())

    en_scale = {
        None: Decimal(1), "k": Decimal(1000), "thousand": Decimal(1000),
        "m": Decimal(1_000_000), "million": Decimal(1_000_000),
        "bn": Decimal(1_000_000_000), "billion": Decimal(1_000_000_000),
        "tn": Decimal(1_000_000_000_000), "trillion": Decimal(1_000_000_000_000),
    }
    for match in _GBP_EN.finditer(text):
        value = _decimal(match.group(1)) * en_scale[(match.group(2) or "").casefold() or None]
        remember(match, "GBP", value)
    for match in _GBP_KO.finditer(text):
        value = (
            (_decimal(match.group("trillion") or "0") * Decimal(1_000_000_000_000))
            + (_decimal(match.group("billion") or "0") * Decimal(100_000_000))
            + (_decimal(match.group("ten_thousand") or "0") * Decimal(10_000))
        )
        remember(match, "GBP", value)
    for match in _PERCENT_POINTS.finditer(text):
        remember(match, "percentage_points", _decimal(match.group(1)))
    for match in _PERCENT.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in consumed):
            continue
        remember(match, "percent", _decimal(match.group(1)))

    # Treat a year-month pair as one typed fact, so 2026-09 and 2026년 9월
    # compare while a wrong month remains visible.
    for match in _KO_MONTH_RANGE.finditer(text):
        start_month = int(match.group(2))
        end_month = int(match.group(3))
        facts.add(("year_month_range", f"{start_month:02d}-{end_month:02d}"))
        facts.add(("calendar_month", f"{start_month:02d}"))
        facts.add(("calendar_month", f"{end_month:02d}"))
        facts.add(("year_month", f"{int(match.group(1)):04d}-{end_month:02d}"))
        consumed.append(match.span())
    for match in _EN_MONTH_RANGE.finditer(text):
        start_month = _EN_MONTHS[match.group(1).casefold()]
        end_month = _EN_MONTHS[match.group(2).casefold()]
        facts.add(("year_month_range", f"{start_month:02d}-{end_month:02d}"))
        facts.add(("calendar_month", f"{start_month:02d}"))
        facts.add(("calendar_month", f"{end_month:02d}"))
        consumed.append(match.span())
    for match in _KO_BARE_MONTH_RANGE.finditer(text):
        start_month, end_month = int(match.group("start")), int(match.group("end"))
        facts.add(("year_month_range", f"{start_month:02d}-{end_month:02d}"))
        facts.add(("calendar_month", f"{start_month:02d}"))
        facts.add(("calendar_month", f"{end_month:02d}"))
        if match.group("year"):
            facts.add(("year_month", f"{match.group('year')}-{end_month:02d}"))
        consumed.append(match.span())
    for match in _KO_YEAR_MONTH.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in consumed):
            continue
        facts.add(("year_month", f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"))
        consumed.append(match.span())
    for match in _EN_YEAR_MONTH.finditer(text):
        month = _EN_MONTHS[match.group(1).casefold()]
        facts.add(("year_month", f"{int(match.group(2)):04d}-{month:02d}"))
        consumed.append(match.span())

    for pattern, group_index in ((_KO_MONTH, 1), (_EN_MONTH, 1)):
        for match in pattern.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in consumed):
                continue
            value = (
                int(match.group(group_index))
                if pattern is _KO_MONTH
                else _EN_MONTHS[match.group(group_index).casefold()]
            )
            facts.add(("calendar_month", f"{value:02d}"))
            consumed.append(match.span())

    for pattern in (_YEAR_OFFSET_EN, _YEAR_OFFSET_KO):
        for match in pattern.finditer(text):
            facts.add(("year_offset", "1"))
            consumed.append(match.span())

    for match in re.finditer(r"\b(\d+)(?:st|nd|rd|th)\b", text, re.IGNORECASE):
        facts.add(("ordinal", str(int(match.group(1)))))
        consumed.append(match.span())
    korean_ordinals = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
    for match in re.finditer(r"(첫|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*번째", text):
        facts.add(("ordinal", str(korean_ordinals[match.group(1)])))
        consumed.append(match.span())

    for match in _NUMBER.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in consumed):
            continue
        value = match.group(0).rstrip("%")
        if value.casefold().endswith("bp"):
            value = value[:-2]
        parsed = _decimal(value)
        if parsed.is_finite():
            facts.add(("number", format(parsed.normalize(), "f")))
    return facts


def _compact(value: str) -> str:
    return re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", value.casefold())


def evaluate_scheduled_evidence(
    imported: Mapping[str, Any],
    *,
    version_sha256: str,
    source_proofs: Mapping[str, Mapping[str, Any]],
    human_review: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate machine-verifiable evidence without impersonating a reviewer.

    When a human review exists, its claim/rights attestations remain accepted.
    Otherwise every source must have exact, current retrieval and reuse-terms
    proof bound to this immutable manuscript version. The caller separately
    enforces target, OAuth, duplicate, policy, and Blogger gates.
    """
    reasons: list[str] = []
    claims = imported.get("claims") or []
    sources = imported.get("sources") or []
    source_by_id = {
        str(source.get("source_id")): source
        for source in sources
        if isinstance(source, Mapping) and source.get("source_id")
    }
    if imported.get("generation_method") != "chatgpt_scheduled_export":
        reasons.append("not_a_scheduled_export")
    if not _SHA256.fullmatch(version_sha256):
        reasons.append("scheduled_version_hash_invalid")
    if not claims or not sources:
        reasons.append("claims_or_sources_missing")

    proof_for_source: dict[str, Mapping[str, Any]] = {}
    for source_id, source in source_by_id.items():
        proof = source_proofs.get(source_id)
        if not proof:
            reasons.append("source_live_verification_missing")
            continue
        if (
            proof.get("http_status") != 200
            or proof.get("source_url") != str(source.get("url"))
            or proof.get("import_id") != str(imported.get("id"))
            or str(proof.get("source_id")) != source_id
            or not _SHA256.fullmatch(str(proof.get("source_body_sha256") or ""))
        ):
            reasons.append("source_live_verification_mismatch")
            continue
        spans = proof.get("verified_claim_evidence")
        if not isinstance(spans, list) or not spans or any(not isinstance(x, str) for x in spans):
            reasons.append("source_evidence_spans_missing")
            continue
        proof_for_source[source_id] = proof

    for claim in claims:
        if not isinstance(claim, Mapping):
            reasons.append("claim_schema_invalid")
            continue
        source_ids = [str(value) for value in (claim.get("source_ids") or [])]
        evidence = str(claim.get("evidence_excerpt") or "").strip()
        if (
            claim.get("verification_status") not in {"source_span_verified", "corroborated"}
            or not source_ids
            or any(source_id not in source_by_id for source_id in source_ids)
        ):
            reasons.append("claim_evidence_incomplete")
            continue
        attached = [proof_for_source.get(source_id) for source_id in source_ids]
        if not evidence or not any(
            proof and any(evidence in str(span) for span in proof.get("verified_claim_evidence", []))
            for proof in attached
        ):
            reasons.append("claim_span_not_found_in_live_source_evidence")
            continue
        evidence_quantities = _quantity_facts(evidence)
        claim_quantities = _quantity_facts(str(claim.get("claim") or ""))
        if not claim_quantities.issubset(evidence_quantities):
            reasons.append("claim_contains_unsupported_number_or_unit")
        if claim.get("verification_status") == "corroborated":
            organizations = {
                str(source_by_id[source_id].get("organization", "")).strip().casefold()
                for source_id in source_ids
                if source_id in source_by_id
            }
            if len(organizations) < 2:
                reasons.append("independent_corroboration_missing")

    human_claims_checked = bool(human_review and human_review.get("claims_checked"))
    human_rights_reviewed = bool(human_review and human_review.get("rights_reviewed"))
    # Exact source spans and numeric/date checks establish traceability only.
    # They cannot establish that a paraphrased sentence means the same thing.
    # Keep that semantic decision separate and fail closed until a reviewer
    # attests to the exact immutable version.
    if not human_claims_checked:
        reasons.append("semantic_claim_review_required")
    if not human_rights_reviewed:
        for source_id, source in source_by_id.items():
            proof = proof_for_source.get(source_id, {})
            terms_expiry_raw = str(proof.get("reuse_policy_expires_at") or "")
            try:
                terms_expiry = datetime.fromisoformat(terms_expiry_raw)
                terms_current = terms_expiry.tzinfo is not None and terms_expiry > datetime.now(UTC)
            except ValueError:
                terms_current = False
            terms_url = str(proof.get("reuse_terms_url") or "")
            terms_url_parts = urlsplit(terms_url)
            if (
                source.get("rights_status") not in {"public_domain", "open_license", "permission_confirmed"}
                or not proof.get("reuse_terms_verified")
                or proof.get("reuse_terms_status") != "allowed"
                or terms_url_parts.scheme != "https"
                or not terms_url_parts.hostname
                or terms_url_parts.username
                or terms_url_parts.password
                or not _SHA256.fullmatch(str(proof.get("reuse_terms_sha256") or ""))
                or not str(proof.get("reuse_policy_id") or "").strip()
                or not str(proof.get("reuse_policy_version") or "").strip()
                or not terms_current
            ):
                reasons.append("source_rights_not_machine_verified")
                break

    unique_reasons = list(dict.fromkeys(reasons))
    evidence_hashes = {
        source_id: {
            "source_body_sha256": str(proof_for_source[source_id].get("source_body_sha256")),
            "reuse_terms_sha256": str(proof_for_source[source_id].get("reuse_terms_sha256") or ""),
            "reuse_policy_id": str(proof_for_source[source_id].get("reuse_policy_id") or ""),
            "reuse_policy_version": str(proof_for_source[source_id].get("reuse_policy_version") or ""),
            "reuse_policy_expires_at": str(proof_for_source[source_id].get("reuse_policy_expires_at") or ""),
        }
        for source_id in sorted(proof_for_source)
    }
    return {
        "status": "passed" if not unique_reasons else "held",
        "reasons": unique_reasons,
        "version_sha256": version_sha256,
        "checks": {
            "source_retrieval_and_hash": not any(
                reason.startswith("source_live_verification") or reason == "source_evidence_spans_missing"
                for reason in unique_reasons
            ),
            "claim_source_spans": not any(
                reason.startswith("claim_") or reason == "claim_evidence_incomplete"
                for reason in unique_reasons
            ),
            "independent_corroboration": "independent_corroboration_missing" not in unique_reasons,
            "rights_terms": "source_rights_not_machine_verified" not in unique_reasons,
            "human_claim_review_present": human_claims_checked,
            "human_rights_review_present": human_rights_reviewed,
            "semantic_claim_review_required": not human_claims_checked,
        },
        "source_ids": sorted(source_by_id),
        "claim_ids": sorted(
            str(claim.get("claim_id")) for claim in claims
            if isinstance(claim, Mapping) and claim.get("claim_id")
        ),
        "source_evidence_sha256": evidence_hashes,
        "claim_count": len(claims),
    }
