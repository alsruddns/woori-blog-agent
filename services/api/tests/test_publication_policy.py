import pytest
from woori.publication_policy import evaluate_publication_content


@pytest.mark.parametrize("lane", ["manual", "scheduled_auto", "trends_auto"])
@pytest.mark.parametrize("reason", [
    "source_original_review_required",
    "claim_source_verification_unavailable",
    "manual_supported_revision_required",
    "source_live_verification_missing",
    "source_evidence_spans_missing",
    "claims_or_sources_not_verified",
    "claims_or_sources_missing",
    "source_rights_not_machine_verified",
    "source_rights_review_incomplete",
    "machine_quality_not_passed",
    "seo_check_not_passed",
    "human_review_pending",
    "research_package_not_reviewed",
])
def test_shared_content_gaps_are_remediations_when_safe_body_remains(lane: str, reason: str) -> None:
    result = evaluate_publication_content([reason], safe_body_available=True)
    assert result["decision"] == "READY_WITH_REMEDIATION", lane
    assert result["safety_blockers"] == []
    assert result["remediation_codes"] == [reason]
    assert len(result["remediation_items"]) == 1


@pytest.mark.parametrize("reason", [
    "source_live_verification_mismatch",
    "claim_contains_unsupported_number_or_unit",
    "source_rights_explicitly_restricted",
    "source_verbatim_excerpt_present",
    "no_supported_body_after_sanitization",
    "blogger_write_oauth_not_verified",
    "same_event_already_queued_or_published",
])
def test_integrity_rights_body_and_operational_failures_stay_blocked(reason: str) -> None:
    result = evaluate_publication_content([reason], safe_body_available=True)
    expected = "POLICY_BLOCKED" if reason in {
        "blogger_write_oauth_not_verified", "same_event_already_queued_or_published",
    } else "SAFETY_HOLD"
    assert result["decision"] == expected
    assert result["blockers"] == [reason]


def test_review_gap_is_not_downgraded_without_safe_sanitized_body() -> None:
    result = evaluate_publication_content(
        ["claim_source_verification_unavailable"], safe_body_available=False,
    )
    assert result["decision"] == "SAFETY_HOLD"
    assert result["safety_blockers"] == ["claim_source_verification_unavailable"]


def test_existing_followups_are_deduplicated() -> None:
    followup = {"issue_type": "number", "severity": "medium",
                "description": "claim_source_verification_unavailable: Some existing note"}
    result = evaluate_publication_content(
        ["claim_source_verification_unavailable"], safe_body_available=True,
        existing_followups=[followup],
    )
    assert result["remediation_items"] == [followup]
