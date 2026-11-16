from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from woori.scheduled_occurrence import (
    deterministic_occurrence_id,
    occurrence_metadata,
    validate_occurrence_metadata,
    verify_configured_slot,
)


def test_derived_occurrence_is_stable_for_same_kst_slot_and_distinct_across_slots() -> None:
    slot = datetime.fromisoformat("2026-10-30T10:30:00+09:00")
    assert deterministic_occurrence_id("automation-3", slot) == (
        "codex-slot:automation-3:20261030T1030KST"
    )
    assert deterministic_occurrence_id(
        "automation-3", datetime.fromisoformat("2026-10-31T10:30:00+09:00")
    ) != deterministic_occurrence_id("automation-3", slot)
    assert deterministic_occurrence_id("automation-4", slot) != deterministic_occurrence_id(
        "automation-3", slot
    )


def test_occurrence_metadata_never_mislabels_derived_id_as_scheduler_issued() -> None:
    slot = datetime.fromisoformat("2026-10-30T10:30:00+09:00")
    derived = occurrence_metadata(automation_id="automation-3", scheduled_slot=slot)
    assert derived == {
        "occurrence_id": "codex-slot:automation-3:20261030T1030KST",
        "occurrence_id_source": "project_derived_kst_slot",
        "scheduler_occurrence_id": None,
        "automation_id": "automation-3",
        "scheduled_slot": "2026-10-30T10:30:00+09:00",
    }
    validate_occurrence_metadata(
        occurrence_id=derived["occurrence_id"],
        occurrence_id_source=derived["occurrence_id_source"],
        scheduler_occurrence_id=derived["scheduler_occurrence_id"],
        automation_id=derived["automation_id"],
        scheduled_slot=slot,
    )

    scheduler = occurrence_metadata(
        automation_id="automation-3",
        scheduled_slot=slot,
        scheduler_occurrence_id="scheduler-run-20261030-1030",
    )
    assert scheduler["occurrence_id"] == "scheduler-run-20261030-1030"
    assert scheduler["occurrence_id_source"] == "scheduler_issued"
    assert scheduler["scheduler_occurrence_id"] == "scheduler-run-20261030-1030"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (datetime(2026, 10, 30, 10, 30), "scheduled_slot_requires_timezone"),
        (
            datetime.fromisoformat("2026-10-30T10:30:00+08:00"),
            "scheduled_slot_timezone_must_be_asia_seoul",
        ),
        (
            datetime.fromisoformat("2026-10-30T10:30:01+09:00"),
            "scheduled_slot_must_use_minute_precision",
        ),
    ],
)
def test_derived_occurrence_rejects_ambiguous_slots(value: datetime, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        deterministic_occurrence_id("automation-3", value)


def test_derived_occurrence_rejects_tampering_and_missing_slot() -> None:
    with pytest.raises(ValueError, match="derived_occurrence_id_does_not_match"):
        validate_occurrence_metadata(
            occurrence_id="made-up-run-id",
            occurrence_id_source="project_derived_kst_slot",
            scheduler_occurrence_id=None,
            automation_id="automation-3",
            scheduled_slot=datetime.fromisoformat("2026-10-30T10:30:00+09:00"),
        )
    with pytest.raises(ValueError, match="derived_occurrence_requires"):
        validate_occurrence_metadata(
            occurrence_id="codex-slot:automation-3:20261030T1030KST",
            occurrence_id_source="project_derived_kst_slot",
            scheduler_occurrence_id=None,
            automation_id="automation-3",
            scheduled_slot=None,
        )


def test_configured_active_automation_must_match_project_and_weekday_slot(tmp_path: Path) -> None:
    project = tmp_path / "checkout"
    project.mkdir()
    automations = tmp_path / "automations"
    task = automations / "automation-3"
    task.mkdir(parents=True)
    (task / "automation.toml").write_text(
        'id = "automation-3"\nkind = "cron"\nstatus = "ACTIVE"\n'
        'rrule = "RRULE:FREQ=DAILY;BYHOUR=10;BYMINUTE=30"\n'
        f'cwds = ["{project.as_posix()}"]\n',
        encoding="utf-8",
    )
    verified = verify_configured_slot(
        automation_id="automation-3",
        scheduled_slot=datetime.fromisoformat("2026-10-30T10:30:00+09:00"),
        automations_root=automations,
        project_root=project,
    )
    assert verified["timezone"] == "Asia/Seoul"
    with pytest.raises(ValueError, match="scheduled_slot_does_not_match_automation_time"):
        verify_configured_slot(
            automation_id="automation-3",
            scheduled_slot=datetime.fromisoformat("2026-10-30T10:31:00+09:00"),
            automations_root=automations,
            project_root=project,
        )
    with pytest.raises(ValueError, match="automation_config_not_bound_to_project"):
        verify_configured_slot(
            automation_id="automation-3",
            scheduled_slot=datetime.fromisoformat("2026-10-30T10:30:00+09:00"),
            automations_root=automations,
            project_root=tmp_path,
        )
