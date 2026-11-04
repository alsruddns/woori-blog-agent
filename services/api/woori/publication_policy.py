"""Shared content-quality policy for manual and automated Blogger lanes.

This module classifies review gaps only. It does not authorize a Blogger write,
promote evidence to verified, or bypass blog/OAuth/duplicate/quota checks.
Callers must pass ``safe_body_available`` only after their lane's evidence-aware
sanitizer and Blogger HTML sanitizer have accepted the exact version.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

CONTENT_REMEDIATIONS: dict[str, tuple[str, str, str]] = {
    "source_original_review_required": ("source", "medium", "\ucd9c\ucc98\u0020\uc6d0\ubb38\u0020\uac80\ud1a0\uac00\u0020\uc644\ub8cc\ub418\uc9c0\u0020\uc54a\uc544\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "source_live_verification_missing": ("source", "medium", "\ucd9c\ucc98\u0020\uc6d0\ubb38\u0020\ud655\uc778\u0020\uc99d\uba85\uc774\u0020\uc5c6\uc5b4\u0020\ubcf4\uc644\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "claim_source_verification_unavailable": ("number", "medium", "\uc77c\ubd80\u0020\uc8fc\uc7a5\uc5d0\u0020\uc5f0\uacb0\ub41c\u0020\uc6d0\ubb38\u0020\uac80\uc99d\u0020\uc790\ub8cc\uac00\u0020\uc5c6\uc5b4\u0020\ubcf4\uc644\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "claim_evidence_incomplete": ("source", "medium", "\uc77c\ubd80\u0020\uc8fc\uc7a5\uacfc\u0020\uadfc\uac70\uc758\u0020\uc5f0\uacb0\uc774\u0020\uc644\ub8cc\ub418\uc9c0\u0020\uc54a\uc544\u0020\ubcf4\uc644\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "source_evidence_spans_missing": ("source", "medium", "\ucd9c\ucc98\u0020\uc6d0\ubb38\uc5d0\uc11c\u0020\ud655\uc778\ud55c\u0020\uadfc\uac70\u0020\uad6c\uac04\uc774\u0020\uc5c6\uc5b4\u0020\ubcf4\uc644\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "semantic_claim_review_required": ("source", "medium", "\uc8fc\uc7a5\uacfc\u0020\ucd9c\ucc98\uc758\u0020\uc758\ubbf8\u0020\uad00\uacc4\ub97c\u0020\ucd94\uac00\u0020\ud655\uc778\ud574\uc57c\u0020\ud569\ub2c8\ub2e4\u002e"),
    "source_review_incomplete": ("source", "medium", "\ucd9c\ucc98\u0020\uac80\ud1a0\uac00\u0020\ubbf8\uc644\ub8cc\ub418\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "reviewed_source_missing": ("source", "medium", "\uac80\ud1a0\ub41c\u0020\ucd9c\ucc98\uac00\u0020\uc5c6\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "evidence_fact_verification_missing": ("number", "medium", "\uc8fc\uc7a5\uacfc\u0020\uadfc\uac70\u0020\uc5f0\uacb0\uc744\u0020\ucd94\uac00\u0020\ud655\uc778\ud574\uc57c\u0020\ud569\ub2c8\ub2e4\u002e"),
    "research_package_not_reviewed": ("source", "medium", "\uc870\uc0ac\u0020\uc790\ub8cc\u0020\uac80\ud1a0\uac00\u0020\ubbf8\uc644\ub8cc\ub418\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "source_rights_review_missing": ("copyright", "medium", "\ucd9c\ucc98\u0020\uc774\uc6a9\u0020\uc870\uac74\u0020\uac80\ud1a0\uac00\u0020\ubbf8\uc644\ub8cc\ub418\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "machine_quality_not_passed": ("other", "medium", "\uae30\uacc4\u0020\ud488\uc9c8\u0020\ud3c9\uac00\uc758\u0020\ubcf4\uc644\u0020\ud56d\ubaa9\uc744\u0020\ud655\uc778\ud574\uc57c\u0020\ud569\ub2c8\ub2e4\u002e"),
    "generation_ready_disabled": ("other", "medium", "\uc6d0\uace0\u0020\uc900\ube44\u0020\ud3c9\uac00\uc758\u0020\ubcf4\uc644\u0020\ud56d\ubaa9\uc744\u0020\ud655\uc778\ud574\uc57c\u0020\ud569\ub2c8\ub2e4\u002e"),
    "publish_ready_disabled": ("other", "medium", "\uc77c\ubc18\u0020\ubc1c\ud589\u0020\uc900\ube44\u0020\ud3c9\uac00\uc758\u0020\ubcf4\uc644\u0020\ud56d\ubaa9\uc744\u0020\ud655\uc778\ud574\uc57c\u0020\ud569\ub2c8\ub2e4\u002e"),
    "seo_check_not_passed": ("other", "low", "\u0053\u0045\u004f\u0020\uc81c\ubaa9\uacfc\u0020\uc124\uba85\u0020\ubc0f\u0020\uac80\uc0c9\uc5b4\u0020\uc0ac\uc6a9\uc744\u0020\ubcf4\uc644\ud574\uc57c\u0020\ud569\ub2c8\ub2e4\u002e"),
    "human_review_pending": ("other", "medium", "\uc77c\ubc18\u0020\ud3b8\uc9d1\u0020\uac80\ud1a0\uac00\u0020\ubbf8\uc644\ub8cc\ub418\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "publication_approval_missing_or_stale": ("other", "medium", "\uc6d0\uace0\ubcc4\u0020\ucd94\uac00\u0020\uc2b9\uc778\uc740\u0020\uc815\ucc45\uc0c1\u0020\uc694\uad6c\ud558\uc9c0\u0020\uc54a\uc73c\uba70\u0020\uae30\uc874\u0020\uc2b9\uc778\u0020\uacf5\ubc31\uc740\u0020\uc774\ub825\uc73c\ub85c\u0020\ub0a8\uae41\ub2c8\ub2e4\u002e"),
    "manual_supported_revision_required": ("source", "medium", "\uac80\uc99d\ub418\uc9c0\u0020\uc54a\uc740\u0020\ubb38\ub2e8\uc740\u0020\uc81c\uc678\ud558\uace0\u0020\uc548\uc804\ud55c\u0020\ubcf8\ubb38\uc73c\ub85c\u0020\ubc1c\ud589\ud588\uc2b5\ub2c8\ub2e4\u002e\u0020\ucd9c\ucc98\u0020\ubcf4\uc644\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "claims_or_sources_not_verified": ("source", "medium", "\uc77c\ubd80\u0020\ucd9c\ucc98\u0020\ub610\ub294\u0020\uc8fc\uc7a5\uc758\u0020\uac80\ud1a0\uac00\u0020\ubbf8\uc644\ub8cc\ub418\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
    "article_quality_review_incomplete": ("other", "medium", "\uc77c\ubc18\u0020\uc6d0\uace0\u0020\ud488\uc9c8\u0020\uac80\ud1a0\uac00\u0020\ubbf8\uc644\ub8cc\ub418\uc5b4\u0020\ucd94\uac00\u0020\ud655\uc778\uc774\u0020\ud544\uc694\ud569\ub2c8\ub2e4\u002e"),
}

POLICY_BLOCKERS = {
    "language_inactive", "blog_inactive", "blog_language_mismatch",
    "blog_connection_unverified", "blog_or_oauth_not_verified",
    "oauth_connection_unavailable", "blogger_write_oauth_not_verified",
    "publication_policy_missing", "publication_policy_inactive",
    "trends_publication_policy_inactive_or_geo_not_allowed",
    "trends_publication_policy_inactive_or_revoked",
    "scheduled_auto_policy_off_or_stopped", "global_emergency_stop_or_policy_missing",
    "publication_emergency_stop_active", "production_writes_disabled",
    "blogger_api_restricted_manual_only", "global_daily_live_publish_limit_reached",
    "trends_daily_publication_limit", "daily_publication_limit",
    "manual_live_job_already_exists", "remote_publication_already_recorded",
    "same_event_already_queued_or_published", "stale_content_version",
    "stale_import_version", "trends_target_mapping_mismatch",
    "scheduled_origin_target_mismatch", "scheduled_language_blog_mismatch",
    "enabled_trend_blog_geo_mapping_required", "blogger_zero_cost_policy_required",
}


def evaluate_publication_content(
    reasons: Iterable[str], *, safe_body_available: bool,
    existing_followups: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Separate remediation gaps from blockers shared by all publication lanes.

    Evidence/review warnings are downgraded only when a usable, evidence-aware
    sanitized body exists. Source mismatch, unsupported core facts, explicit
    rights restrictions, malformed HTML, and empty-body reasons are deliberately
    absent from the remediation map and remain blockers.
    """
    blockers: list[str] = []
    followups = [dict(item) for item in existing_followups]
    seen = {(item.get("issue_type"), item.get("description")) for item in followups}
    remediation_codes: list[str] = []
    for raw_reason in reasons:
        reason = str(raw_reason)
        mapping = CONTENT_REMEDIATIONS.get(reason)
        if mapping and (safe_body_available or reason == "manual_supported_revision_required"):
            issue_type, severity, description = mapping
            coded_description = f"{reason}: {description}"
            key = (issue_type, coded_description)
            already_recorded = key in seen or any(
                item.get("issue_type") == issue_type
                and str(item.get("description") or "").startswith(f"{reason}:")
                for item in followups
            )
            if not already_recorded:
                followups.append({"issue_type": issue_type, "severity": severity,
                                  "description": coded_description})
                seen.add(key)
            remediation_codes.append(reason)
        else:
            blockers.append(reason)
    unique_blockers = list(dict.fromkeys(blockers))
    policy_reasons = [reason for reason in unique_blockers if reason in POLICY_BLOCKERS]
    safety_blockers = [reason for reason in unique_blockers if reason not in POLICY_BLOCKERS]
    decision = "POLICY_BLOCKED" if policy_reasons else "SAFETY_HOLD" if safety_blockers else (
        "READY_WITH_REMEDIATION" if followups else "READY"
    )
    return {
        "decision": decision,
        "remediation_items": followups,
        "remediation_codes": list(dict.fromkeys(remediation_codes)),
        "safety_blockers": safety_blockers,
        "policy_reasons": policy_reasons,
        "blockers": unique_blockers,
    }
