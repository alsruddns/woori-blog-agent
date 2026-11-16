"""Fail-closed classification of a Codex Desktop Local Automation invocation.

The resolver reads only the current Codex Desktop session transcript selected by
CODEX_THREAD_ID. Its local session format is not a publication attestation; the
result is recorded as self-reported provenance and never grants Auto rights.
"""

from __future__ import annotations

import json
import os
import re
import time
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from .scheduled_occurrence import occurrence_metadata, verify_configured_slot

_KST = ZoneInfo("Asia/Seoul")
_AUTOMATION_LINE = re.compile(r"(?m)^Automation ID:\s*([A-Za-z0-9_.:-]+)\s*$")


def _codex_home(environ: Mapping[str, str]) -> Path:
    """Resolve Codex Desktop data without requiring CODEX_HOME to be exported.

    An explicit environment value remains authoritative. When it is absent,
    Codex Desktop's per-user default is used; callers still fail closed if the
    expected session or automation record is missing below that directory.
    """
    configured = environ.get("CODEX_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


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


def _read_invocation_events(path: Path) -> list[dict[str, Any]]:
    """Stream only the transcript records needed to identify the current turn."""
    events: list[dict[str, Any]] = []
    max_line_bytes = 16 * 1024 * 1024
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if len(line.encode("utf-8")) > max_line_bytes:
                raise ValueError("codex_session_event_too_large")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                if not line.endswith("\n"):
                    raise ValueError("codex_session_transcript_incomplete") from exc
                raise
            if not isinstance(record, dict):
                continue
            payload = record.get("payload")
            if (record.get("type") == "session_meta"
                    or (record.get("type") == "event_msg" and isinstance(payload, dict)
                        and payload.get("type") in {"task_started", "task_complete"})):
                events.append(record)
            elif (record.get("type") == "response_item" and isinstance(payload, dict)
                  and payload.get("type") == "message" and payload.get("role") == "user"):
                ids = _automation_id_from_message(record)
                if ids:
                    events.append({
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"text": f"Automation ID: {value}"} for value in ids],
                        },
                    })
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


def _automation_id_from_message(record: dict[str, Any]) -> list[str]:
    return _AUTOMATION_LINE.findall(_text_from_user_message(record))


def _current_automation_start(
    records: list[dict[str, Any]],
    *,
    automation_id: str | None = None,
    current_turn_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Select the current unfinished turn, not every turn in a reused thread.

    Codex Desktop appends later turns to a Local Automation session transcript.
    A completed scheduled turn therefore remains beside a later Run now or
    composer turn. The last unfinished task_started event is the only candidate
    for the resolver currently running inside that turn. Its own Automation ID
    prompt and turn identity must match before the trigger is trusted.
    """
    starts = [
        (index, record.get("payload", {}))
        for index, record in enumerate(records)
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_started"
    ]
    if not starts:
        raise ValueError("current_automation_start_event_not_found")

    completions = [
        (index, record.get("payload", {}))
        for index, record in enumerate(records)
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    completed_turn_ids = {
        payload.get("turn_id") for _, payload in completions
        if isinstance(payload.get("turn_id"), str)
    }

    def start_turn_id(payload: dict[str, Any]) -> str | None:
        attribution = payload.get("turn_attribution")
        attributed = attribution.get("turn_id") if isinstance(attribution, dict) else None
        top_level = payload.get("turn_id")
        if isinstance(top_level, str) and isinstance(attributed, str) and top_level != attributed:
            raise ValueError("current_automation_start_event_ambiguous")
        value = top_level if isinstance(top_level, str) else attributed
        return value if isinstance(value, str) else None

    active = [
        (index, payload) for index, payload in starts
        if start_turn_id(payload) is not None
        and start_turn_id(payload) not in completed_turn_ids
    ]
    if len(active) > 1:
        raise ValueError("current_automation_start_event_ambiguous")
    # Older transcript formats may not expose a top-level turn ID. In that
    # case only the final event can be considered, and attribution must still
    # provide a stable turn ID below.
    candidate = active[-1] if active else starts[-1]
    index, payload = candidate
    attribution = payload.get("turn_attribution")
    attributed_turn_id = attribution.get("turn_id") if isinstance(attribution, dict) else None
    trigger = attribution.get("turn_trigger") if isinstance(attribution, dict) else None
    if trigger not in {"automation_cron_scheduled", "automation_cron_run_now"}:
        raise ValueError("current_automation_trigger_unrecognized")
    event_turn_id = payload.get("turn_id")
    if (isinstance(event_turn_id, str) and isinstance(attributed_turn_id, str)
            and event_turn_id != attributed_turn_id):
        raise ValueError("current_automation_start_event_ambiguous")
    turn_id = event_turn_id if isinstance(event_turn_id, str) else attributed_turn_id
    if not isinstance(turn_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", turn_id):
        raise ValueError("current_automation_start_event_ambiguous")
    if current_turn_id and current_turn_id != turn_id:
        raise ValueError("current_codex_turn_id_mismatch")
    if sum(1 for _, started in starts if start_turn_id(started) == turn_id) != 1:
        raise ValueError("current_automation_start_event_ambiguous")
    if turn_id in completed_turn_ids:
        raise ValueError("current_automation_run_not_active")

    next_turn_index = min(
        (other_index for other_index, _ in starts if other_index > index),
        default=len(records),
    )
    next_completion_index = min(
        (complete_index for complete_index, complete in completions
         if complete_index > index and complete.get("turn_id") == turn_id),
        default=len(records),
    )
    segment_end = min(next_turn_index, next_completion_index)
    prompt_ids = [
        automation for message_index, record in enumerate(records)
        if index < message_index < segment_end
        for automation in _automation_id_from_message(record)
    ]
    if not prompt_ids:
        raise ValueError("current_automation_start_event_pending")
    if len(prompt_ids) != 1:
        raise ValueError("current_session_automation_id_missing_or_ambiguous")
    resolved_id = prompt_ids[0]
    if automation_id is not None and resolved_id != automation_id:
        raise ValueError("current_session_automation_id_mismatch")
    return resolved_id, payload


def _read_current_automation_start(
    session_path: Path,
    *,
    automation_id: str | None = None,
    current_turn_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Re-read a just-started transcript briefly; never spawn another process."""
    last_error: ValueError | None = None
    for attempt in range(4):
        try:
            records = _read_invocation_events(session_path)
        except ValueError as exc:
            if str(exc) != "codex_session_transcript_incomplete" or attempt == 3:
                raise
            last_error = exc
            time.sleep(0.15)
            continue
        try:
            return _current_automation_start(
                records,
                automation_id=automation_id,
                current_turn_id=current_turn_id,
            )
        except ValueError as exc:
            last_error = exc
            if str(exc) not in {
                "current_automation_start_event_not_found",
                "current_automation_start_event_pending",
            } or attempt == 3:
                raise
            time.sleep(0.15)
    if last_error is not None:
        raise last_error
    raise ValueError("current_automation_start_event_not_found")


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


def current_automation_id(
    *,
    project_root: Path,
    sessions_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Read the exact Automation ID from this verified Desktop session prompt."""
    env = os.environ if environ is None else environ
    thread_id = env.get("CODEX_THREAD_ID", "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", thread_id):
        raise ValueError("current_codex_thread_id_unavailable")
    codex_root = _codex_home(env)
    sessions_root = sessions_root or codex_root / "sessions"
    matches = list(sessions_root.rglob(f"*{thread_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError("current_codex_session_record_missing_or_ambiguous")
    records = _read_invocation_events(matches[0])
    meta = next((r.get("payload") for r in records if r.get("type") == "session_meta"), None)
    if not isinstance(meta, dict) or (
        meta.get("session_id") != thread_id
        or meta.get("originator") != "Codex Desktop"
        or meta.get("thread_source") != "automation"
    ):
        raise ValueError("current_session_is_not_codex_desktop_automation")
    if Path(str(meta.get("cwd", ""))).resolve(strict=True) != project_root.resolve(strict=True):
        raise ValueError("current_automation_checkout_mismatch")
    turn_id = env.get("CODEX_TURN_ID") or env.get("CODEX_CURRENT_TURN_ID")
    resolved_id, _ = _read_current_automation_start(
        matches[0], current_turn_id=turn_id or None,
    )
    return resolved_id


def _configured_slot_near(timestamp: datetime, automation_id: str, config: dict[str, Any],
                          automations_root: Path, project_root: Path) -> datetime:
    local = timestamp.astimezone(_KST)
    # RRULE slots have minute precision. Compare against the same precision;
    # otherwise 12:05:02 is incorrectly treated as 302 seconds from 12:00.
    slot_reference = local.replace(second=0, microsecond=0)
    candidates: list[datetime] = []
    for offset in range(-5, 6):
        candidate = slot_reference + timedelta(minutes=offset)
        try:
            verify_configured_slot(
                automation_id=automation_id, scheduled_slot=candidate,
                automations_root=automations_root, project_root=project_root,
            )
        except (OSError, ValueError):
            continue
        if abs((candidate - slot_reference).total_seconds()) <= 300:
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
    codex_root = _codex_home(env)
    automations_root = automations_root or codex_root / "automations"
    sessions_root = sessions_root or codex_root / "sessions"
    config = _automation_config(automation_id, automations_root, project_root)
    matches = list(sessions_root.rglob(f"*{thread_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError("current_codex_session_record_missing_or_ambiguous")
    records = _read_invocation_events(matches[0])
    session_meta = next((r.get("payload") for r in records if r.get("type") == "session_meta"), None)
    if not isinstance(session_meta, dict):
        raise TypeError("codex_session_metadata_missing")
    if (session_meta.get("session_id") != thread_id
            or session_meta.get("originator") != "Codex Desktop"
            or session_meta.get("thread_source") != "automation"):
        raise ValueError("current_session_is_not_codex_desktop_automation")
    if Path(str(session_meta.get("cwd", ""))).resolve(strict=True) != project_root.resolve(strict=True):
        raise ValueError("current_automation_checkout_mismatch")
    turn_id = env.get("CODEX_TURN_ID") or env.get("CODEX_CURRENT_TURN_ID")
    _, start_event = _read_current_automation_start(
        matches[0], automation_id=automation_id, current_turn_id=turn_id or None,
    )
    attribution = start_event.get("turn_attribution")
    trigger = attribution.get("turn_trigger") if isinstance(attribution, dict) else None
    started = start_event.get("started_at")
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
    current_turn = start_event.get("turn_id")
    if not isinstance(current_turn, str) and isinstance(attribution, dict):
        current_turn = attribution.get("turn_id")
    if not isinstance(current_turn, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", current_turn):
        raise ValueError("current_automation_turn_identity_missing")
    manual_uuid = uuid5(NAMESPACE_URL, f"woori-blog-agent:{automation_id}:{current_turn}")
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
