from woori.publication_policy import evaluate_publication_content
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


def test_manual_intent_uses_same_evidence_proof_without_fake_human_review():
    imported, proof = _scheduled_fixture()
    imported["generation_method"] = "manual_codex_import"
    result = evaluate_scheduled_evidence(
        imported, version_sha256="b" * 64, source_proofs=proof,
        human_review=None, scheduled_publish_first=True,
        article_body="The rate was reported. [source:S1]",
        expected_generation_method="manual_codex_import",
    )
    assert result["status"] == "passed"
    assert result["checks"]["human_claim_review_present"] is False
    assert result["followups"]
    imported["claims"][0]["verification_status"] = "unverified"
    held = evaluate_scheduled_evidence(
        imported, version_sha256="b" * 64, source_proofs=proof,
        human_review=None, scheduled_publish_first=True,
        article_body="The rate was reported. [source:S1]",
        expected_generation_method="manual_codex_import",
    )
    assert "claim_evidence_incomplete" in held["reasons"]


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
    assert "source_rights_explicitly_restricted" in result["reasons"]
    imported["claims"][0]["factual_state"] = "unverified"
    assert verified_scheduled_claim_ids(imported, proof) == set()


def test_scheduled_sanitizer_retains_uncited_and_unverified_content_as_followups():
    claims = [
        {"claim_id": "C1", "source_ids": ["S1"], "factual_state": "enacted",
         "verification_status": "source_span_verified"},
        {"claim_id": "C2", "source_ids": ["S2"], "factual_state": "unverified",
         "verification_status": "source_span_verified"},
    ]
    body = "# Evidence\n\nA supported paragraph. [source:S1]\n\nAn unsupported paragraph. [source:S2]\n\nUncited factual paragraph."
    result = sanitize_scheduled_body(body, claims, verified_claim_ids={"C1"})
    assert result["changed"] is False
    assert "A supported paragraph." in result["body_markdown"]
    assert "unsupported paragraph" in result["body_markdown"]
    assert "Uncited factual paragraph" in result["body_markdown"]
    warning_reasons = {reason for item in result["retained_warnings"] for reason in item["reasons"]}
    assert warning_reasons == {
        "source_or_claim_verification_incomplete_retained",
        "source_rights_review_incomplete_retained",
        "uncited_paragraph_retained_for_review",
    }
    assert result["removed_blocks"] == []


def test_scheduled_sanitizer_retains_body_when_live_proof_is_missing():
    imported, _ = _scheduled_fixture()
    result = sanitize_scheduled_body(
        "A long paragraph with no usable support. [source:S1]", imported["claims"],
        verified_claim_ids=set(),
    )
    assert "A long paragraph with no usable support." in result["body_markdown"]
    assert result["substantive_blocks_remaining"] == 1
    assert result["retained_warnings"]


def test_missing_source_and_rights_records_remain_followups_with_publishable_body():
    imported, _proofs = _scheduled_fixture()
    imported["claims"][0]["verification_status"] = "unverified"
    body = (
        "The agency announced a policy change for local residents. [source:S1]\n\n"
        "The change will take effect after a public consultation period. [source:S1]\n\n"
        "Officials said implementation details remain under discussion. [source:S1]"
    )
    sanitized = sanitize_scheduled_body(
        body, imported["claims"], verified_claim_ids=set(),
        source_rights={"S1": "quotation_review_required"},
    )
    evidence = evaluate_scheduled_evidence(
        imported, version_sha256="b" * 64, source_proofs={}, human_review=None,
        scheduled_publish_first=True, article_body=sanitized["body_markdown"],
    )
    policy = evaluate_publication_content(
        [*evidence["reasons"], *(reason for warning in sanitized["retained_warnings"]
                                 for reason in warning["reasons"])],
        safe_body_available=sanitized["substantive_blocks_remaining"] >= 2,
        existing_followups=evidence["followups"],
    )
    assert policy["decision"] == "READY_WITH_REMEDIATION"
    assert policy["safety_blockers"] == []
    assert "source_live_verification_missing" in policy["remediation_codes"]
    assert "claim_evidence_incomplete" in policy["remediation_codes"]
    assert evidence["checks"]["human_rights_review_present"] is False


def test_scheduled_sanitizer_removes_verbatim_excerpt_but_keeps_surrounding_body():
    claims = [{
        "claim_id": "C1", "source_ids": ["S1"], "factual_state": "enacted",
        "verification_status": "source_span_verified",
        "evidence_excerpt": "The published rate was 2 percent.",
    }]
    body = (
        "The agency announced a policy. The published rate was 2 percent. [source:S1]\n\n"
        "A separate explanation helps readers understand the event. [source:S1]"
    )
    result = sanitize_scheduled_body(body, claims, verified_claim_ids={"C1"})
    assert "The agency announced a policy." in result["body_markdown"]
    assert "The published rate was 2 percent." not in result["body_markdown"]
    assert "A separate explanation" in result["body_markdown"]
    assert "source_excerpt_removed" in {
        reason for block in result["removed_blocks"] for reason in block["reasons"]
    }


def test_scheduled_sanitizer_strips_quoted_span_without_erasing_article_paragraph():
    result = sanitize_scheduled_body(
        'The club won the match. "A long direct quotation from a source appears here." '
        'The result changes the table. [source:S1]', [],
    )
    assert "The club won the match." in result["body_markdown"]
    assert "The result changes the table." in result["body_markdown"]
    assert "A long direct quotation" not in result["body_markdown"]
    assert result["substantive_blocks_remaining"] == 1
    assert "quoted_text_removed" in {
        reason for block in result["removed_blocks"] for reason in block["reasons"]
    }


def test_scheduled_sanitizer_keeps_empty_original_as_empty():
    result = sanitize_scheduled_body("   ", [], verified_claim_ids=set())
    assert result["body_markdown"] == ""
    assert result["substantive_blocks_remaining"] == 0


def test_scheduled_sanitizer_removes_only_confirmed_false_claim_paragraph():
    claims = [
        {"claim_id": "false-1", "source_ids": ["S1"], "claim": "The product was banned by law.",
         "factual_state": "contradicted", "verification_status": "contradicted"},
        {"claim_id": "ok-1", "source_ids": ["S2"], "claim": "The company reported a new product.",
         "factual_state": "enacted", "verification_status": "unverified"},
    ]
    body = (
        "The product was banned by law. [source:S1]\n\n"
        "The company reported a new product. [source:S2]"
    )
    result = sanitize_scheduled_body(body, claims, verified_claim_ids=set())
    assert "banned by law" not in result["body_markdown"]
    assert "reported a new product" in result["body_markdown"]
    assert result["removed_claim_ids"] == ["false-1"]
    assert result["substantive_blocks_remaining"] == 1


def test_scheduled_sanitizer_removes_content_for_explicit_rights_restriction_only():
    claims = [{"claim_id": "C1", "source_ids": ["S1"], "claim": "Restricted source claim.",
               "factual_state": "enacted", "verification_status": "unverified"}]
    result = sanitize_scheduled_body(
        "Restricted source claim. [source:S1]\n\nIndependent editorial context without the restricted source.",
        claims, source_rights={"S1": "permission_required"},
    )
    assert "Restricted source claim" not in result["body_markdown"]
    assert "Independent editorial context" in result["body_markdown"]
    assert result["removed_claim_ids"] == ["C1"]
