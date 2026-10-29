from __future__ import annotations

from woori.scheduled_auto_verification import evaluate_scheduled_evidence


def _case() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    imported: dict[str, object] = {
        "id": "import-1",
        "generation_method": "chatgpt_scheduled_export",
        "sources": [{
            "source_id": "source-1",
            "url": "https://official.example.gov/release/1",
            "organization": "Official Agency",
            "rights_status": "open_license",
        }],
        "claims": [{
            "claim_id": "claim-1",
            "claim": "The agency reported 12.5 percent.",
            "source_ids": ["source-1"],
            "evidence_excerpt": "The agency reported 12.5 percent.",
            "verification_status": "source_span_verified",
        }],
    }
    proofs = {
        "source-1": {
            "source_id": "source-1",
            "import_id": "import-1",
            "source_url": "https://official.example.gov/release/1",
            "http_status": 200,
            "source_body_sha256": "a" * 64,
            "verified_claim_evidence": ["The agency reported 12.5 percent."],
            "reuse_terms_verified": True,
            "reuse_terms_status": "allowed",
            "reuse_terms_url": "https://official.example.gov/reuse",
            "reuse_terms_sha256": "b" * 64,
            "reuse_policy_id": "example-official-reuse",
            "reuse_policy_version": "1",
            "reuse_policy_expires_at": "2099-01-01T00:00:00Z",
        }
    }
    return imported, proofs


def test_scheduled_machine_evidence_can_pass_without_fabricating_human_review() -> None:
    imported, proofs = _case()
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "passed"
    assert result["checks"]["human_claim_review_present"] is False
    assert result["checks"]["human_rights_review_present"] is False
    assert result["claim_ids"] == ["claim-1"]
    assert result["source_evidence_sha256"]["source-1"]["source_body_sha256"] == "a" * 64


def test_scheduled_machine_evidence_holds_unknown_rights() -> None:
    imported, proofs = _case()
    imported["sources"][0]["rights_status"] = "quotation_review_required"
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "source_rights_not_machine_verified" in result["reasons"]


def test_scheduled_machine_evidence_holds_expired_reuse_policy() -> None:
    imported, proofs = _case()
    proofs["source-1"]["reuse_policy_expires_at"] = "2000-01-01T00:00:00Z"
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "source_rights_not_machine_verified" in result["reasons"]


def test_scheduled_machine_evidence_holds_unmatched_claim_or_hash() -> None:
    imported, proofs = _case()
    imported["claims"][0]["claim"] = "The agency reported 13 percent."
    result = evaluate_scheduled_evidence(
        imported, version_sha256="not-a-sha", source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "scheduled_version_hash_invalid" in result["reasons"]
    assert "claim_contains_unsupported_number" in result["reasons"]
    assert "claim_not_supported_by_exact_source_span" in result["reasons"]


def test_corroborated_claim_requires_distinct_organizations() -> None:
    imported, proofs = _case()
    imported["claims"][0]["verification_status"] = "corroborated"
    imported["claims"][0]["source_ids"] = ["source-1", "source-1"]
    result = evaluate_scheduled_evidence(
        imported, version_sha256="c" * 64, source_proofs=proofs, human_review=None,
    )
    assert result["status"] == "held"
    assert "independent_corroboration_missing" in result["reasons"]
