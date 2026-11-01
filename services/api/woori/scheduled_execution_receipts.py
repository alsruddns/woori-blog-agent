"""Local execution identity receipts, never source/fact/publication approval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .automation_invocation import resolve_current_invocation

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
        actual = resolve_current_invocation(
            str(metadata["automation_id"]),
            project_root=ROOT,
            environ={"CODEX_THREAD_ID": receipt["session_id"]},
        )
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
