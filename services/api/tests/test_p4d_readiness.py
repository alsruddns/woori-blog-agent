from __future__ import annotations

from typing import Any

from woori import research_routes


class FakeConnection:
    def execute(self, _sql: str) -> Any:
        return type("Result", (), {"fetchone": lambda _self: {
            "attempts": 1,
            "non_mock_attempts": 0,
            "mock_successes": 1,
            "mock_non_successes": 0,
        }})()


def make_state(reviews: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    articles = [
        {"evaluation_id": f"fed-{language}", "language_code": language, "machine_passed": True}
        for language in ("en", "ko", "ja", "zh-CN")
    ]
    return {
        "profiles": [
            {"language_code": language, "target_country": "", "active": True}
            for language in ("en", "ko", "ja", "zh-CN")
        ],
        "evaluation_results": {
            "fed_articles": articles,
            "sec_new_inference": "not_run_quota_blocked",
            "sec_c3_runs": [],
        },
        "article_reviews": reviews or [],
        "cost_policy": {
            "blocked_credential_names": [],
            "providers": [{
                "name": "google_blogger_read",
                "calls_allowed": False,
                "block_reason": "manual_zero_cost_review_required",
            }],
        },
        "prepublication": {
            "blogs": [
                {"active": True, "url": f"https://blog-{n}.example", "blog_id": f"id-{n}",
                 "oauth_status": "connected", "scopes": ["https://www.googleapis.com/auth/blogger.readonly"]}
                for n in range(4)
            ],
            "real_blogger_sync_verified": False,
            "real_writes_enabled": False,
            "safety": {
                "non_mock_jobs": 0,
                "real_publishing_records": 0,
                "publish_ready_evaluations": 0,
            },
        },
    }


def test_readiness_is_fail_closed_and_distinguishes_machine_human_and_live_gates(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        research_routes,
        "_worker_recovery_evidence",
        lambda: {"passed": True, "artifact_count": 1, "scope": "historical isolated test"},
    )
    result = research_routes._operational_readiness_snapshot(FakeConnection(), make_state())
    items = {item["key"]: item for item in result["items"]}

    assert items["fed_machine"]["status"] == "passed"
    assert items["fed_human"]["status"] == "pending"
    assert items["sec_machine"]["status"] == "blocked_not_run_quota_exhausted"
    assert items["blogger_cost"]["status"] == "blocked_provider_cost_unverified"
    assert items["blogger_read_connection"]["status"] == "configured_live_read_blocked"
    assert items["publication_mock"]["status"] == "verified"
    assert items["worker_recovery"]["status"] == "verified_historical"
    assert items["operating_write_block"]["status"] == "blocked_safe"
    assert items["separate_live_publication_approval"]["status"] == "required_not_granted"


def test_editorial_review_does_not_grant_live_publication(monkeypatch: Any) -> None:
    monkeypatch.setattr(research_routes, "_worker_recovery_evidence", lambda: {"passed": False})
    reviews = [
        {"evaluation_id": f"fed-{language}", "disposition": "approved",
         "factual_accuracy": "verified", "translation_naturalness": "acceptable",
         "reader_value": "useful"}
        for language in ("en", "ko", "ja", "zh-CN")
    ]
    result = research_routes._operational_readiness_snapshot(FakeConnection(), make_state(reviews))
    items = {item["key"]: item for item in result["items"]}
    assert items["fed_human"]["status"] == "editorially_approved"
    assert items["fed_human"]["evidence"].startswith("4/4 reviewed")
    assert items["separate_live_publication_approval"]["status"] == "required_not_granted"


def test_readiness_tracks_new_active_language_without_fixed_language_count(monkeypatch: Any) -> None:
    monkeypatch.setattr(research_routes, "_worker_recovery_evidence", lambda: {"passed": False})
    state = make_state()
    state["profiles"].append({"language_code": "es", "target_country": "", "active": True})
    result = research_routes._operational_readiness_snapshot(FakeConnection(), state)
    fed_machine = next(item for item in result["items"] if item["key"] == "fed_machine")
    assert fed_machine["status"] == "incomplete"
    assert fed_machine["evidence"].startswith("4/5 active base-profile languages")
