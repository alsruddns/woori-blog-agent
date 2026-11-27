"""Local execution identity receipts, never source/fact/publication approval."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]


def _path(occurrence_id: str, *, create: bool = True) -> Path:
    from .scheduled_import_inbox import _is_reparse_point

    base = ROOT / ".local/gpt-scheduled-import"
    for folder in (base.parent, base, base / "execution_receipts"):
        if _is_reparse_point(folder):
            raise ValueError("unsafe_execution_receipt_directory")
        if create:
            folder.mkdir(exist_ok=True)
    return (
        base / "execution_receipts" / (hashlib.sha256(occurrence_id.encode()).hexdigest() + ".json")
    )


def record(invocation: dict[str, Any]) -> None:
    if invocation.get("execution_mode") != "scheduled":
        return
    from .scheduled_import_inbox import _is_reparse_point
    from .scheduled_pending import _exclusive_json

    path = _path(invocation["occurrence_id"])
    value = {
        key: invocation[key]
        for key in (
            "execution_mode",
            "automation_id",
            "session_id",
            "scheduled_slot",
            "occurrence_id",
            "occurrence_id_source",
            "scheduler_occurrence_id",
            "executed_at",
        )
    }
    if path.exists():
        if _is_reparse_point(path) or json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError("execution_receipt_identity_conflict")
        return
    try:
        _exclusive_json(path, value)
    except FileExistsError:
        record(invocation)


def verify(metadata: dict[str, Any]) -> bool:
    from .scheduled_import_inbox import _is_reparse_point

    try:
        path = _path(str(metadata["occurrence_id"]), create=False)
        if _is_reparse_point(path) or path.stat().st_size > 8192:
            return False
        receipt = json.loads(path.read_text(encoding="utf-8"))
        actual = _verify_recorded_turn(receipt)
        if (
            actual.get("execution_mode") != "scheduled"
            or receipt.get("execution_mode") != "scheduled"
        ):
            return False
        return all(
            actual.get(k) == receipt.get(k) == metadata.get(k)
            for k in (
                "automation_id",
                "scheduled_slot",
                "occurrence_id",
                "occurrence_id_source",
                "scheduler_occurrence_id",
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _verify_recorded_turn(receipt: dict[str, Any]) -> dict[str, Any]:
    """Recheck the exact recorded scheduled turn after its session completes."""
    from .automation_invocation import (
        _automation_config,
        _codex_home,
        _configured_slot_near,
        _current_automation_start,
        _read_invocation_events,
    )
    from .scheduled_occurrence import occurrence_metadata

    home = _codex_home({})
    session = str(receipt["session_id"])
    if str(UUID(session)) != session.lower():
        raise ValueError("receipt_session_identity_invalid")
    paths = list((home / "sessions").rglob(f"*{session}.jsonl"))
    if len(paths) != 1:
        raise ValueError("receipt_session_missing_or_ambiguous")
    records = _read_invocation_events(paths[0])
    meta = next((r.get("payload") for r in records if r.get("type") == "session_meta"), None)
    if (not isinstance(meta, dict) or meta.get("session_id") != session
            or meta.get("originator") != "Codex Desktop" or meta.get("thread_source") != "automation"
            or Path(str(meta.get("cwd", ""))).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise ValueError("receipt_session_identity_invalid")
    started_at = datetime.fromisoformat(str(receipt["executed_at"])).astimezone(UTC)
    starts = [(i, r["payload"]) for i, r in enumerate(records)
              if r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "task_started"
              and isinstance(r["payload"].get("started_at"), (int, float))
              and datetime.fromtimestamp(r["payload"]["started_at"], UTC) == started_at]
    if len(starts) != 1:
        raise ValueError("receipt_turn_missing_or_ambiguous")
    index, start = starts[0]
    end = next((i for i in range(index + 1, len(records)) if records[i].get("type") == "event_msg"
                and records[i].get("payload", {}).get("type") == "task_started"), len(records))
    segment = [r for r in records[index:end] if not (r.get("type") == "event_msg"
               and r.get("payload", {}).get("type") == "task_complete")]
    _, selected = _current_automation_start(segment, automation_id=str(receipt["automation_id"]))
    if selected != start or selected.get("turn_attribution", {}).get("turn_trigger") != "automation_cron_scheduled":
        raise ValueError("receipt_turn_not_scheduled")
    automations = home / "automations"
    config = _automation_config(str(receipt["automation_id"]), automations, ROOT)
    slot = _configured_slot_near(started_at, str(receipt["automation_id"]), config, automations, ROOT)
    return {"execution_mode": "scheduled", "automation_id": receipt["automation_id"],
            **occurrence_metadata(automation_id=str(receipt["automation_id"]), scheduled_slot=slot)}
