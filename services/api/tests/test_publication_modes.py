from pathlib import Path

import pytest


def test_mode_migration_is_additive_manual_by_default_and_live_auto_locked() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "scripts/042_publication_modes.sql").read_text(encoding="utf-8").casefold()
    runner = (root / "scripts/migrate.py").read_text(encoding="utf-8")
    assert "configured_mode text not null default 'manual'" in migration
    assert "operations_auto_approved boolean not null default false check (not operations_auto_approved)" in migration
    assert "values('global','','manual',false)" in migration
    assert "insert into schema_migrations(version) values(42)" in migration
    assert "042_publication_modes.sql" in runner
    scheduled = (root / "scripts/052_scheduled_publication_approval.sql").read_text(encoding="utf-8").casefold()
    assert "operations_auto_approved boolean" not in scheduled
    assert "scheduled_publication_policy_events" in scheduled
    assert "scheduled_first_publication_events" in scheduled
    assert "publication_lane text not null default 'manual'" in scheduled
    assert "create trigger scheduled_publication_policy_events_immutable" in scheduled
    assert "052_scheduled_publication_approval.sql" in runner
    assert "auto_publish_allowed" not in migration
    assert "drop table" not in migration and "delete from" not in migration
    assert "check (not auto_publish_allowed)" not in migration


def test_scheduled_auto_confirmation_is_explicit_and_scoped() -> None:
    from pydantic import ValidationError
    from woori.publications import ScheduledAutoPolicyInput

    with pytest.raises(ValidationError):
        ScheduledAutoPolicyInput(
            action="enable", blog_ids=[], actor_label="operator", reason="approved policy",
            idempotency_key="scheduled-policy-test-01", confirmation="yes",
        )
    request = ScheduledAutoPolicyInput(
        action="enable", blog_ids=[], actor_label="operator", reason="approved policy",
        idempotency_key="scheduled-policy-test-01",
        confirmation="ENABLE SCHEDULED AUTO PUBLICATION",
    )
    assert request.action == "enable"


def test_dashboard_publication_proxy_only_exposes_mode_write_and_stop_routes() -> None:
    root = Path(__file__).resolve().parents[3]
    proxy = (root / "apps/dashboard/app/api/publications/[[...path]]/route.ts").read_text(encoding="utf-8")
    assert 'route === "mode-settings"' in proxy
    assert 'route === "emergency-stop"' in proxy
    assert 'request.method === "PUT"' in proxy
    assert 'request.method === "POST"' in proxy
    assert 'request.method === "DELETE" && /^jobs\\/[a-f0-9-]+\\/schedule$/.test(route)' in proxy
    assert "export const DELETE = proxy" in proxy
    assert 'route === "requests"' in proxy
