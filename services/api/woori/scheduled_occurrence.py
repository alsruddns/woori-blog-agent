"""Stable identities for Codex Local scheduled-task occurrences.

Codex Desktop does not currently expose a scheduler-issued occurrence ID in
the task prompt.  The project can therefore use the actual local Automation ID
and configured KST slot as a deterministic fallback.  This identifies a
scheduled slot; it does not attest that Codex itself verified the task run.
"""

from __future__ import annotations

import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

SCHEDULE_TIMEZONE = "Asia/Seoul"
_SCHEDULE_ZONE = ZoneInfo(SCHEDULE_TIMEZONE)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SCHEDULER_ID = re.compile(r"^[A-Za-z0-9_.:-]{8,160}$")
OccurrenceSource = Literal["scheduler_issued", "project_derived_kst_slot"]


def normalize_kst_slot(value: datetime) -> datetime:
    """Require a minute-precision KST schedule slot and normalize its tzinfo."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduled_slot_requires_timezone")
    local = value.astimezone(_SCHEDULE_ZONE)
    if value.utcoffset() != local.utcoffset():
        raise ValueError("scheduled_slot_timezone_must_be_asia_seoul")
    if local.second or local.microsecond:
        raise ValueError("scheduled_slot_must_use_minute_precision")
    return local


def deterministic_occurrence_id(automation_id: str, scheduled_slot: datetime) -> str:
    """Return a stable project-derived ID for one configured Codex KST slot."""
    if not _SAFE_ID.fullmatch(automation_id):
        raise ValueError("automation_id_invalid")
    local = normalize_kst_slot(scheduled_slot)
    return f"codex-slot:{automation_id}:{local:%Y%m%dT%H%M}KST"


def occurrence_metadata(
    *,
    automation_id: str,
    scheduled_slot: datetime,
    scheduler_occurrence_id: str | None = None,
) -> dict[str, Any]:
    """Build the envelope fields without implying a provider ID was supplied."""
    local = normalize_kst_slot(scheduled_slot)
    if scheduler_occurrence_id is not None:
        if not _SCHEDULER_ID.fullmatch(scheduler_occurrence_id):
            raise ValueError("scheduler_occurrence_id_invalid")
        return {
            "occurrence_id": scheduler_occurrence_id,
            "occurrence_id_source": "scheduler_issued",
            "scheduler_occurrence_id": scheduler_occurrence_id,
            "automation_id": automation_id,
            "scheduled_slot": local.isoformat(),
        }
    return {
        "occurrence_id": deterministic_occurrence_id(automation_id, local),
        "occurrence_id_source": "project_derived_kst_slot",
        "scheduler_occurrence_id": None,
        "automation_id": automation_id,
        "scheduled_slot": local.isoformat(),
    }


def validate_occurrence_metadata(
    *,
    occurrence_id: str,
    occurrence_id_source: OccurrenceSource | None,
    scheduler_occurrence_id: str | None,
    automation_id: str | None,
    scheduled_slot: datetime | None,
) -> None:
    """Validate new metadata while accepting legacy envelopes with no metadata."""
    fields = (scheduler_occurrence_id, automation_id, scheduled_slot)
    if occurrence_id_source is None:
        if any(value is not None for value in fields):
            raise ValueError("occurrence_metadata_source_required")
        return
    if occurrence_id_source == "scheduler_issued":
        if not scheduler_occurrence_id or not _SCHEDULER_ID.fullmatch(scheduler_occurrence_id):
            raise ValueError("scheduler_occurrence_id_required")
        if occurrence_id != scheduler_occurrence_id:
            raise ValueError("scheduler_occurrence_id_must_match_occurrence_id")
        if automation_id is not None and not _SAFE_ID.fullmatch(automation_id):
            raise ValueError("automation_id_invalid")
        if scheduled_slot is not None:
            normalize_kst_slot(scheduled_slot)
        return
    if scheduler_occurrence_id is not None:
        raise ValueError("derived_occurrence_must_not_claim_scheduler_id")
    if not automation_id or scheduled_slot is None:
        raise ValueError("derived_occurrence_requires_automation_id_and_scheduled_slot")
    expected = deterministic_occurrence_id(automation_id, scheduled_slot)
    if occurrence_id != expected:
        raise ValueError("derived_occurrence_id_does_not_match_configured_kst_slot")


def verify_configured_slot(
    *,
    automation_id: str,
    scheduled_slot: datetime,
    automations_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Read the real Codex Automation TOML and confirm its project and KST slot."""
    local = normalize_kst_slot(scheduled_slot)
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in automations_root.rglob("automation.toml"):
        try:
            config = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            continue
        if config.get("id") == automation_id:
            matches.append((path, config))
    if len(matches) != 1:
        raise ValueError("automation_config_not_found_or_ambiguous")
    path, config = matches[0]
    if config.get("status") != "ACTIVE" or config.get("kind") != "cron":
        raise ValueError("automation_config_not_active_cron")
    project = str(project_root.resolve(strict=True)).casefold()
    configured_cwds = config.get("cwds")
    resolved_cwds: set[str] = set()
    if isinstance(configured_cwds, list):
        for cwd in configured_cwds:
            if not isinstance(cwd, str):
                continue
            try:
                resolved_cwds.add(Path(cwd).resolve(strict=True).as_posix().casefold())
            except OSError:
                continue
    if Path(project).as_posix().casefold() not in resolved_cwds:
        raise ValueError("automation_config_not_bound_to_project_checkout")
    _validate_rrule_slot(config.get("rrule"), local)
    return {
        "automation_id": automation_id,
        "scheduled_slot": local.isoformat(),
        "timezone": SCHEDULE_TIMEZONE,
        "automation_config_path": str(path),
    }


def _validate_rrule_slot(value: object, slot: datetime) -> None:
    if not isinstance(value, str) or not value.startswith("RRULE:"):
        raise ValueError("automation_rrule_missing")
    fields: dict[str, str] = {}
    for part in value.removeprefix("RRULE:").split(";"):
        if "=" not in part:
            raise ValueError("automation_rrule_invalid")
        key, item = part.split("=", 1)
        fields[key] = item
    frequency = fields.get("FREQ")
    try:
        hour = int(fields["BYHOUR"])
        minute = int(fields["BYMINUTE"])
    except (KeyError, ValueError) as exc:
        raise ValueError("automation_rrule_slot_missing") from exc
    if (slot.hour, slot.minute) != (hour, minute):
        raise ValueError("scheduled_slot_does_not_match_automation_time")
    if frequency == "DAILY":
        return
    if frequency != "WEEKLY":
        raise ValueError("automation_rrule_frequency_not_supported_for_occurrence")
    day_codes = fields.get("BYDAY", "").split(",")
    weekday_codes = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    if not day_codes or any(code not in weekday_codes for code in day_codes):
        raise ValueError("automation_rrule_weekday_not_supported")
    if weekday_codes[slot.weekday()] not in day_codes:
        raise ValueError("scheduled_slot_does_not_match_automation_weekday")
