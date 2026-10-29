from woori.publication_worker import scheduled_publish_first_assessment
from woori.scheduled_auto_verification import (
    evaluate_scheduled_evidence,
    sanitize_scheduled_body,
    verified_scheduled_claim_ids,
)


def _scheduled_fixture(rights_status: str = "quotation_review_required"):
    imported = {
        "id": "import-1",
        "generation_method": "chatgpt_scheduled_export",
        "claims": [{
            "claim_id": "C1", "claim": "The rate is 2 percent.",
            "evidence_excerpt": "The published rate was 2 percent.",
            "source_ids": ["S1"], "verification_status": "source_span_verified",
            "factual_state": "enacted",
        }],
        "sources": [{
            "source_id": "S1", "url": "https://example.gov/release",
            "organization": "Example Ministry", "rights_status": rights_status,
        }],
    }
    proof = {
        "S1": {
            "http_status": 200, "source_url": "https://example.gov/release",
            "source_id": "S1", "import_id": "import-1", "source_body_sha256": "a" * 64,
            "verified_claim_evidence": ["The published rate was 2 percent."],
            "reuse_terms_status": "unknown",
        }
    }
    return imported, proof


def test_scheduled_publish_first_allows_minor_review_followups_only():
    imported, proof = _scheduled_fixture()
    result = evaluate_scheduled_evidence(
        imported, version_sha256="b" * 64, source_proofs=proof,
        human_review=None, scheduled_publish_first=True,
        article_body="The rate was reported. [source:S1]",
    )
    assert result["status"] == "passed"
    assert "semantic_claim_review_required" not in result["reasons"]
    assert any(item["issue_type"] == "copyright" for item in result["followups"])


def test_scheduled_publish_first_routes_failed_quality_flags_to_followups_without_mutating_them():
    reasons, followups = scheduled_publish_first_assessment({
        "machine_passed": False,
        "generation_ready": False,
        "publish_ready": False,
        "safe_html": "<p>Evidence-backed original summary.</p>",
    })
    assert reasons == []
    assert {item["description"] for item in followups} == {
        "기계 품질 검사 미통과", "원고 생성 준비 평가 미통과", "일반 publish_ready 평가 미통과",
    }


def test_scheduled_publish_first_still_blocks_when_no_sanitized_html_exists():
    reasons, followups = scheduled_publish_first_assessment({
        "machine_passed": True, "generation_ready": True, "publish_ready": True,
        "safe_html": None,
    })
    assert reasons == ["scheduled_publishable_html_missing"]
    assert followups == []


def test_scheduled_publish_first_still_blocks_restricted_rights_and_unverified_facts():
    imported, proof = _scheduled_fixture("restricted")
    result = evaluate_scheduled_evidence(
        imported, version_sha256="b" * 64, source_proofs=proof,
        human_review=None, scheduled_publish_first=True,
        article_body="The rate was reported. [source:S1]",
    )
    assert "source_rights_not_machine_verified" in result["reasons"]
    imported["claims"][0]["factual_state"] = "unverified"
    assert verified_scheduled_claim_ids(imported, proof) == set()


def test_scheduled_sanitizer_removes_uncited_and_unverified_source_blocks():
    claims = [
        {"claim_id": "C1", "source_ids": ["S1"], "factual_state": "enacted",
         "verification_status": "source_span_verified"},
        {"claim_id": "C2", "source_ids": ["S2"], "factual_state": "unverified",
         "verification_status": "source_span_verified"},
    ]
    body = "# Evidence\n\nA supported paragraph. [source:S1]\n\nAn unsupported paragraph. [source:S2]\n\nUncited factual paragraph."
    result = sanitize_scheduled_body(body, claims, verified_claim_ids={"C1"})
    assert result["changed"] is True
    assert "A supported paragraph." in result["body_markdown"]
    assert "unsupported paragraph" not in result["body_markdown"]
    assert "Uncited factual paragraph" not in result["body_markdown"]
    assert len(result["removed_blocks"]) == 2


def test_scheduled_sanitizer_drops_body_when_no_claim_has_live_evidence():
    imported, _ = _scheduled_fixture()
    result = sanitize_scheduled_body(
        "A long paragraph with no usable support. [source:S1]", imported["claims"],
        verified_claim_ids=set(),
    )
    assert result["body_markdown"] == ""
    assert result["substantive_blocks_remaining"] == 0


def test_scheduled_sanitizer_removes_verbatim_evidence_and_direct_quotes():
    claims = [{
        "claim_id": "C1", "source_ids": ["S1"], "factual_state": "enacted",
        "verification_status": "source_span_verified",
        "evidence_excerpt": "The published rate was 2 percent.",
    }]
    body = (
        "The published rate was 2 percent. [source:S1]\n\n"
        "‘Quoted wording that should not be republished.’ [source:S1]"
    )
    result = sanitize_scheduled_body(body, claims, verified_claim_ids={"C1"})
    assert result["body_markdown"] == ""
    assert {reason for block in result["removed_blocks"] for reason in block["reasons"]} == {
        "direct_quote_removed", "source_excerpt_copy_removed",
    }
