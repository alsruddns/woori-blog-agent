"""Fail-closed lifecycle status metadata for evidence-backed article claims."""

from __future__ import annotations

import re
from typing import Any

CLAIM_STATUSES = frozenset(
    {"proposed", "planned", "approved", "enacted", "paid", "unverified"}
)

STATUS_RULES = {
    "proposed": "Describe only as proposed or advocated; do not imply approval, enactment, or payment.",
    "planned": "Describe only as planned or scheduled; do not imply implementation or completion.",
    "approved": "Use approved only when the reviewed evidence explicitly supports approval.",
    "enacted": "Use enacted only when reviewed evidence explicitly establishes enactment and any stated effective date.",
    "paid": "Use paid only when reviewed evidence explicitly establishes disbursement.",
    "unverified": "Do not assert a lifecycle status; omit it or clearly state that the status is unverified.",
}

_STATUS_RANK = {
    "unverified": -1,
    "proposed": 0,
    "planned": 1,
    "approved": 2,
    "enacted": 3,
    "paid": 4,
}
_STATUS_TERMS = {
    "proposed": r"\bpropos(?:e|ed|al)\b|提案|提出|제안|추진안",
    "planned": r"\bplan(?:ned)?\b|\bscheduled\b|\bwill take effect\b|予定|計画|規劃|規划|예정|계획",
    "approved": r"\bapproved?\b|\bpassed\b|核准|批准|通過|通过|승인|가결|통과|承認|可決",
    "enacted": r"\benacted\b|\bin effect\b|\btook effect\b|\bimplemented\b|施行|實施|实施|生效|시행|발효|施行|実施|発効",
    "paid": r"\bpaid\b|\bdisbursed\b|\bpayment made\b|發放|支付|撥付|发放|拨付|지급|집행|지불|支給|支払",
}


def prepare_claim_for_generation(fact: dict[str, Any]) -> dict[str, Any]:
    """Attach a reviewed status without allowing the model to promote it.

    A non-unverified status must be explicitly human-reviewed and point to an
    exact supporting excerpt already present in the fact span. This is a
    provenance guard, not an automatic semantic verification.
    """
    status = str(fact.get("claim_status") or "unverified")
    if status not in CLAIM_STATUSES:
        raise ValueError("claim_status_invalid")
    excerpt = str(fact.get("text") or fact.get("source_excerpt") or "")
    basis = str(fact.get("claim_status_basis_excerpt") or "")
    reviewed = fact.get("claim_status_reviewed") is True
    if status != "unverified" and (not reviewed or not basis or basis not in excerpt):
        raise ValueError("claim_status_evidence_missing")
    return {
        **fact,
        "claim_status": status,
        "claim_status_rule": STATUS_RULES[status],
        "claim_status_basis_excerpt": basis if reviewed else "",
    }


def prepare_claims_for_generation(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [prepare_claim_for_generation(fact) for fact in facts]


def lifecycle_status_violations(text: str, facts: list[dict[str, Any]]) -> list[str]:
    """Conservatively detect lifecycle claims that exceed reviewed fact status."""
    statuses = [str(fact.get("claim_status") or "unverified") for fact in facts]
    if not statuses:
        return ["claim_status_facts_missing"]
    if any(status not in _STATUS_RANK for status in statuses):
        return ["claim_status_invalid"]
    highest_allowed = min(_STATUS_RANK[status] for status in statuses)
    matched = [
        (status, pattern)
        for status, pattern in _STATUS_TERMS.items()
        if re.search(pattern, text, re.IGNORECASE)
    ]
    violations = [
        f"claim_status_exceeds_{status}"
        for status, _ in matched
        if _STATUS_RANK[status] > highest_allowed
    ]
    return violations
