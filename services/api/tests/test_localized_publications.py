from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from woori.localized_publications import (
    LocalizedCancellationInput,
    LocalizedRequestInput,
    _initial_state,
    recommended_language,
)


def test_region_recommendations_are_limited_to_unambiguous_matches() -> None:
    assert recommended_language("US") == ("en", "direct_region_language_match")
    assert recommended_language("KR") == ("ko", "direct_region_language_match")
    assert recommended_language("JP") == ("ja", "direct_region_language_match")
    assert recommended_language("CN") == ("zh-CN", "direct_region_language_match")
    for region in ("TW", "HK", "SG"):
        language, reason = recommended_language(region)
        assert language is None
        assert reason == "regional_language_and_reader_relevance_require_editorial_selection"
    assert recommended_language("XX")[0] is None


def test_localized_request_requires_explicit_confirmation_and_unique_targets() -> None:
    common = {
        "evaluation_id": uuid4(),
        "source_content_version_id": uuid4(),
        "targets": [
            {"language_code": "en", "blog_id": uuid4(), "selection_reason": "This event affects English readers directly."},
            {"language_code": "ja", "blog_id": uuid4(), "selection_reason": "This issue has a verified impact in Japan."},
        ],
        "requester": "Editor",
        "idempotency_key": "request-key-0001",
    }
    with pytest.raises(ValidationError, match="explicit_confirmation"):
        LocalizedRequestInput(**common, explicit_confirmation=False)
    valid = LocalizedRequestInput(**common, explicit_confirmation=True)
    assert valid.one_time_auto_publish_requested is False
    duplicate_target = common["targets"][0]
    with pytest.raises(ValidationError, match="duplicate_language_blog_target"):
        LocalizedRequestInput(
            **{**common, "targets": [duplicate_target, duplicate_target]},
            explicit_confirmation=True,
        )


def test_request_cancellation_requires_actor_reason_and_idempotency_key() -> None:
    valid = LocalizedCancellationInput(
        actor="Editor", reason="Please stop this language extension request.",
        idempotency_key="cancel-request-0001",
    )
    assert valid.actor == "Editor"
    with pytest.raises(ValidationError):
        LocalizedCancellationInput(actor="E", reason="short", idempotency_key="bad")


@pytest.mark.parametrize(
    ("source", "existing", "expected"),
    [
        ({"source_is_evaluation_only": True, "source_provenance_verified": True, "evaluation": {"machine_passed": True}}, [], "blocked_evaluation_only"),
        ({"source_is_evaluation_only": False, "source_provenance_verified": False, "evaluation": {"machine_passed": True}}, [], "blocked_source_provenance_unverified"),
        ({"source_is_evaluation_only": False, "source_provenance_verified": True, "evaluation": {"machine_passed": False}}, [], "blocked_source_quality"),
        ({"source_is_evaluation_only": False, "source_provenance_verified": True, "evaluation": {"machine_passed": True}}, [{"content_version_id": str(uuid4())}], "existing_localization_requires_review"),
        ({"source_is_evaluation_only": False, "source_provenance_verified": True, "evaluation": {"machine_passed": True}}, [], "awaiting_provider"),
    ],
)
def test_request_state_fails_closed(source: dict, existing: list[dict], expected: str) -> None:
    state, _blockers = _initial_state(source, existing)
    assert state == expected


def test_migration_is_additive_append_only_and_never_enables_live_publishing() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/043_localized_publication_requests.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    proxy = (root / "apps/dashboard/app/api/research/[...path]/route.ts").read_text(encoding="utf-8")
    assert "insert into schema_migrations(version) values(43)" in migration
    assert "unique(source_group_id,target_language_code,target_blog_id)" in migration
    assert "localized_publication_request_immutable" in migration
    assert "localized_publication_event_immutable" in migration
    assert "live_blogger_writes_enabled\":false" in migration
    assert "043_localized_publication_requests.sql" in runner
    recovery = (root / "scripts/044_localized_request_recovery.sql").read_text(encoding="utf-8").casefold()
    assert "drop constraint" in recovery and '"cancelled_requests_can_be_retried":true' in recovery
    assert "version_localization<>new.source_localization_id" in recovery
    assert "044_localized_request_recovery.sql" in runner
    module = (root / "services/api/woori/localized_publications.py").read_text(encoding="utf-8")
    assert '"candidate_language_decisions": candidate_decisions' in module
    assert '"selection_reason": selection_reasons.get' in module
    assert '"not_selected_by_user"' in module
    assert '"no_active_language_blog_mapping"' in module
    assert '@router.post("/requests/{request_id}/cancel")' in module
    assert r"localized-publications\/requests\/[0-9a-f-]{36}\/cancel" in proxy
    assert "delete from" not in migration and "drop table" not in migration
