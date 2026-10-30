"""Fail-closed classification of a Codex Desktop Local Automation invocation.

The resolver reads only the current Codex Desktop session transcript selected by
CODEX_THREAD_ID. Its local session format is not a publication attestation; the
result is recorded as self-reported provenance and never grants Auto rights.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from .scheduled_occurrence import occurrence_metadata, verify_configured_slot

_KST = ZoneInfo("Asia/Seoul")
_AUTOMATION_LINE = re.compile(r"(?m)^Automation ID:\s*([A-Za-z0-9_.:-]+)\s*$")


def _read_events(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("codex_session_transcript_too_large")
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                events.append(record)
    return events


def _text_from_user_message(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(item.get("text", "")) for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )


def _automation_config(automation_id: str, automations_root: Path, project_root: Path) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    project = project_root.resolve(strict=True).as_posix().casefold()
    for path in automations_root.rglob("automation.toml"):
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            continue
        if value.get("id") != automation_id:
            continue
        cwds = value.get("cwds")
        resolved = set()
        if isinstance(cwds, list):
            for cwd in cwds:
                if isinstance(cwd, str):
                    try:
                        resolved.add(Path(cwd).resolve(strict=True).as_posix().casefold())
                    except OSError:
                        pass
        if value.get("status") != "ACTIVE" or value.get("kind") != "cron" or project not in resolved:
            raise ValueError("automation_config_inactive_or_project_mismatch")
        matches.append(value)
    if len(matches) != 1:
        raise ValueError("automation_config_missing_or_ambiguous")
    return matches[0]


def _configured_slot_near(timestamp: datetime, automation_id: str, config: dict[str, Any],
                          automations_root: Path, project_root: Path) -> datetime:
    local = timestamp.astimezone(_KST)
    candidates: list[datetime] = []
    for offset in range(-5, 6):
        candidate = local.replace(second=0, microsecond=0) + timedelta(minutes=offset)
        try:
            verify_configured_slot(
                automation_id=automation_id, scheduled_slot=candidate,
                automations_root=automations_root, project_root=project_root,
            )
        except (OSError, ValueError):
            continue
        if abs((candidate - local).total_seconds()) <= 300:
            candidates.append(candidate)
    if len(candidates) != 1:
        raise ValueError("scheduled_slot_not_unambiguously_near_actual_invocation")
    return candidates[0]


def _recent_quota_recovery(
    automation_id: str,
    *,
    automations_root: Path,
    sessions_root: Path,
    project_root: Path,
    now: datetime,
) -> dict[str, Any] | None:
    cutoff = now.astimezone(UTC) - timedelta(days=14)
    candidates: list[dict[str, Any]] = []
    config = _automation_config(automation_id, automations_root, project_root)
    files = sorted(sessions_root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files[:300]:
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                break
            records = _read_events(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        meta_record = next((r.get("payload") for r in records if r.get("type") == "session_meta"), None)
        if not isinstance(meta_record, dict) or meta_record.get("thread_source") != "automation":
            continue
        try:
            if Path(str(meta_record.get("cwd", ""))).resolve(strict=True) != project_root.resolve(strict=True):
                continue
        except OSError:
            continue
        messages = "\n".join(_text_from_user_message(r) for r in records)
        if _AUTOMATION_LINE.findall(messages) != [automation_id]:
            continue
        starts = [r.get("payload", {}) for r in records
                  if r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "task_started"]
        completes = [r.get("payload", {}) for r in records
                     if r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "task_complete"]
        if len(starts) != 1 or len(completes) != 1:
            continue
        attribution = starts[0].get("turn_attribution")
        completion_error = completes[0].get("error")
        if (not isinstance(attribution, dict)
                or attribution.get("turn_trigger") != "automation_cron_scheduled"
                or not isinstance(completion_error, dict)
                or completion_error.get("codex_error_info") != "usage_limit_exceeded"):
            continue
        started = starts[0].get("started_at")
        turn_id = attribution.get("turn_id")
        if not isinstance(started, (int, float)) or not isinstance(turn_id, str):
            continue
        try:
            session_id = str(UUID(str(meta_record.get("session_id", ""))))
        except ValueError:
            continue
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", turn_id):
            continue
        try:
            slot = _configured_slot_near(datetime.fromtimestamp(started, UTC), automation_id,
                                         config, automations_root, project_root)
        except (OSError, ValueError):
            continue
        candidates.append({
            "recovery_of_session_id": session_id,
            "recovery_of_turn_id": turn_id,
            "recovery_of_scheduled_slot": slot.isoformat(),
            "recovery_reason_code": "usage_limit_exceeded",
        })
    if len(candidates) == 1:
        return candidates[0]
    return None


def resolve_current_invocation(
    automation_id: str,
    *,
    project_root: Path,
    automations_root: Path | None = None,
    sessions_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return scheduled/manual only for an exact current-thread trigger record."""
    env = os.environ if environ is None else environ
    thread_id = env.get("CODEX_THREAD_ID", "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", thread_id):
        raise ValueError("current_codex_thread_id_unavailable")
    codex_root = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
    automations_root = automations_root or codex_root / "automations"
    sessions_root = sessions_root or codex_root / "sessions"
    config = _automation_config(automation_id, automations_root, project_root)
    matches = list(sessions_root.rglob(f"*{thread_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError("current_codex_session_record_missing_or_ambiguous")
    records = _read_events(matches[0])
    session_meta = next((r.get("payload") for r in records if r.get("type") == "session_meta"), None)
    if not isinstance(session_meta, dict):
        raise TypeError("codex_session_metadata_missing")
    if (session_meta.get("session_id") != thread_id
            or session_meta.get("originator") != "Codex Desktop"
            or session_meta.get("thread_source") != "automation"):
        raise ValueError("current_session_is_not_codex_desktop_automation")
    if Path(str(session_meta.get("cwd", ""))).resolve(strict=True) != project_root.resolve(strict=True):
        raise ValueError("current_automation_checkout_mismatch")
    text = "\n".join(_text_from_user_message(r) for r in records)
    ids = _AUTOMATION_LINE.findall(text)
    if ids != [automation_id]:
        raise ValueError("current_session_automation_id_mismatch")
    starts = [r.get("payload", {}) for r in records
              if r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "task_started"]
    if len(starts) != 1:
        raise ValueError("current_automation_start_event_missing_or_ambiguous")
    attribution = starts[0].get("turn_attribution")
    trigger = attribution.get("turn_trigger") if isinstance(attribution, dict) else None
    started = starts[0].get("started_at")
    if not isinstance(started, (int, float)) or trigger not in {
        "automation_cron_scheduled", "automation_cron_run_now",
    }:
        raise ValueError("current_automation_trigger_unrecognized")
    started_at = datetime.fromtimestamp(started, UTC).astimezone(_KST)
    common: dict[str, Any] = {
        "automation_id": automation_id,
        "session_id": thread_id,
        "executed_at": started_at.isoformat(),
        "trigger": trigger,
        "evidence_source": "codex_desktop_local_session_record",
        "provenance_self_reported": True,
    }
    if trigger == "automation_cron_scheduled":
        slot = _configured_slot_near(started_at, automation_id, config, automations_root, project_root)
        common.update({"execution_mode": "scheduled", **occurrence_metadata(
            automation_id=automation_id, scheduled_slot=slot,
        )})
        return common
    manual_uuid = uuid5(NAMESPACE_URL, f"woori-blog-agent:{automation_id}:{thread_id}")
    manual_run_id = f"codex-manual:{automation_id}:{manual_uuid}"
    common.update({
        "execution_mode": "manual",
        "manual_run_id": manual_run_id,
        "manual_origin": {
            "execution_mode": "manual",
            "automation_id": automation_id,
            "manual_run_id": manual_run_id,
            "session_id": thread_id,
            "turn_trigger": trigger,
            "invoked_at": started_at.isoformat(),
        },
    })
    recovery = _recent_quota_recovery(
        automation_id, automations_root=automations_root, sessions_root=sessions_root,
        project_root=project_root, now=started_at,
    )
    if recovery:
        common["manual_origin"].update(recovery)
    return common
