"""Assess untrusted claims against retained collector evidence without granting approval."""

from __future__ import annotations

import re
from typing import Any

from .scheduled_auto_verification import _quantity_facts, excerpt_supported


def assess_claim_evidence(imported: dict[str, Any], proofs: dict[str, Any]) -> dict[str, Any]:
    sources = {str(s.get("source_id")): s for s in (imported.get("sources") or []) if isinstance(s, dict)}
    results = []
    for claim in (imported.get("claims") or []):
        if not isinstance(claim, dict):
            results.append({"claim_id": None, "source_span_confirmed": False,
                            "verification_status": "unverified", "reasons": ["claim_schema_invalid"]})
            continue
        reasons = []
        matched = []
        excerpt = str(claim.get("evidence_excerpt") or "").strip()
        source_ids = claim.get("source_ids") or []
        if not excerpt or not source_ids:
            reasons.append("claim_evidence_missing")
        for source_id in source_ids:
            source, proof = sources.get(str(source_id)), proofs.get(str(source_id), {})
            if (not source or proof.get("http_status") != 200
                    or proof.get("source_url") != source.get("url")
                    or str(proof.get("import_id")) != str(imported.get("id"))
                    or str(proof.get("source_id")) != str(source_id)
                    or not re.fullmatch(r"[a-f0-9]{64}", str(proof.get("source_body_sha256") or ""))):
                reasons.append("source_retrieval_proof_missing_or_mismatched")
                continue
            if not excerpt_supported(excerpt, proof.get("verified_claim_evidence") or []):
                reasons.append("evidence_excerpt_not_in_source")
                continue
            matched.append(str(source_id))
        if not _quantity_facts(str(claim.get("claim") or "")).issubset(_quantity_facts(excerpt)):
            reasons.append("claim_number_or_date_not_in_evidence")
        # Exact evidence establishes traceability, not entailment or rights.
        reasons.extend(["semantic_claim_review_required", "rights_review_required"])
        results.append({"claim_id": claim.get("claim_id"), "matched_source_ids": matched,
                        "source_span_confirmed": bool(matched) and len(set(reasons)) == 2,
                        "verification_status": "unverified", "reasons": sorted(set(reasons))})
    return {"policy_version": "claim-evidence-1", "claims": results,
            "claim_count": len(results), "source_span_confirmed_count": sum(r["source_span_confirmed"] for r in results),
            "verified_count": 0, "manual_review_required": True, "publish_eligible": False}
