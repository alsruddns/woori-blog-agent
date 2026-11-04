"""Fail-closed, exclusive handoff of a verified Automation import to ready/."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from .content_imports import ManualAutomationImportEnvelope, ScheduledImportEnvelope
from .scheduled_import_inbox import (
    MAX_FILE_BYTES,
    _is_reparse_point,
    _safe_directories,
    validate_envelope,
)


def _origin(envelope: ScheduledImportEnvelope | ManualAutomationImportEnvelope) -> Any:
    return (
        envelope.scheduled_origin
        if isinstance(envelope, ScheduledImportEnvelope)
        else envelope.manual_origin
    )


def invocation_matches(
    envelope: ScheduledImportEnvelope | ManualAutomationImportEnvelope, invocation: dict[str, Any]
) -> bool:
    """Require an exact resolver result; prompt text or a claimed mode is insufficient."""
    origin = _origin(envelope)
    if isinstance(envelope, ScheduledImportEnvelope):
        return bool(
            invocation.get("execution_mode") == "scheduled"
            and invocation.get("trigger") == "automation_cron_scheduled"
            and invocation.get("automation_id") == origin.automation_id
            and invocation.get("occurrence_id") == origin.occurrence_id
            and invocation.get("scheduled_slot") == origin.scheduled_slot.isoformat()
        )
    return bool(
        invocation.get("execution_mode") == "manual"
        and invocation.get("trigger") == "automation_cron_run_now"
        and invocation.get("automation_id") == origin.automation_id
        and invocation.get("session_id") == str(origin.session_id)
        and invocation.get("manual_run_id") == origin.manual_run_id
        and invocation.get("manual_origin") == origin.model_dump(mode="json", exclude_none=True)
    )


def preflight_allows_import(result: dict[str, Any]) -> bool:
    """Only definite local absence/failure-only permits a new original Import.

    Remote duplicate state is intentionally not inferred here; the import and
    publication paths preserve their own checks. ``unknown`` never permits a
    handoff even when the CLI's overall status is ambiguous.
    """
    return bool(
        result.get("local_status") in {"not_found", "failed_only"}
        and result.get("draft_import_allowed") is True
        and result.get("remote_status") == "not_checked"
    )


def handoff_incoming(
    root: Path, source: Path, *, invocation: dict[str, Any], preflight: dict[str, Any]
) -> dict[str, Any]:
    """Validate and atomically expose one incoming file without overwriting ready/.

    The source bytes are linked into ready/ with an exclusive hard-link create,
    then the incoming name is removed. This is same-volume and fails closed if
    the filesystem cannot provide exclusive hard-link semantics.
    """
    directories = _safe_directories(root)
    incoming = directories["incoming"]
    ready = directories["ready"]
    if _is_reparse_point(root) or _is_reparse_point(incoming) or _is_reparse_point(source):
        raise ValueError("automation_import_path_must_not_be_reparse_point")
    source_path = source.resolve(strict=True)
    if source_path.parent != incoming.resolve(strict=True) or source_path.suffix != ".part":
        raise ValueError("requires_safe_incoming_part")
    size = source_path.stat().st_size
    if not 0 < size <= MAX_FILE_BYTES:
        raise ValueError("automation_import_file_size_invalid")
    raw = source_path.read_bytes()
    envelope = validate_envelope(raw)
    if not invocation_matches(envelope, invocation):
        raise ValueError("automation_import_invocation_mismatch")
    if not preflight_allows_import(preflight):
        raise ValueError("automation_import_duplicate_preflight_not_clear")

    target = ready / f"{source_path.stem}.ready.json"
    # os.link is exclusive: an existing destination is never replaced.
    os.link(source_path, target)
    try:
        source_path.unlink()
    except OSError as exc:
        raise OSError("ready_published_incoming_cleanup_failed") from exc
    return {
        "handed_off": True,
        "execution_mode": "scheduled"
        if isinstance(envelope, ScheduledImportEnvelope)
        else "manual",
        "automation_id": _origin(envelope).automation_id,
        "ready_file": str(target),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "import_status": "awaiting_research_worker",
        "publication_created": False,
        "blogger_write_count": 0,
    }
