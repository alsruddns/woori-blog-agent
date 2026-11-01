"""Immutable outage manuscripts and authenticated, transactional recovery.

Neither local saving nor recovery creates publication work or opens sources.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from . import content_imports as imports
from .automation_invocation import resolve_current_invocation
from .db import connection
from .scheduled_import_inbox import (
    ImportEnvelope,
    _is_reparse_point,
    _safe_directories,
    validate_envelope,
)
from .scheduled_occurrence import verify_configured_slot

router = APIRouter()
ROOT = Path(__file__).resolve().parents[3]
MAX_AGE = timedelta(hours=24)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def identity(envelope: ImportEnvelope, target_blog_id: str | None = None) -> tuple[str, str, str]:
    if isinstance(envelope, imports.ScheduledImportEnvelope):
        origin = envelope.scheduled_origin
        if not origin.automation_id or origin.scheduled_slot is None:
            raise ValueError("pending_requires_verified_configured_slot")
        verify_configured_slot(
            automation_id=origin.automation_id,
            scheduled_slot=origin.scheduled_slot,
            automations_root=Path.home() / ".codex" / "automations",
            project_root=ROOT,
        )
        return "scheduled", origin.occurrence_id, origin.target_blog_id
    if (
        not target_blog_id
        or not target_blog_id.isascii()
        or not target_blog_id.isdigit()
        or not 5 <= len(target_blog_id) <= 32
    ):
        raise ValueError("manual_pending_requires_target_blog_id")
    return "manual", envelope.manual_origin.manual_run_id, target_blog_id


def pending_key(envelope: ImportEnvelope, target_blog_id: str | None = None) -> str:
    mode, run, blog = identity(envelope, target_blog_id)
    return hashlib.sha256(canonical([mode, run, blog, envelope.item.language_code])).hexdigest()


def verify_saved_invocation(envelope: ImportEnvelope, evidence: dict[str, Any] | None) -> bool:
    """Re-read the actual Desktop trigger; configured RRULE alone is not a run."""
    if not evidence or not isinstance(evidence.get("session_id"), str):
        return False
    origin = (
        envelope.scheduled_origin
        if isinstance(envelope, imports.ScheduledImportEnvelope)
        else envelope.manual_origin
    )
    try:
        actual = resolve_current_invocation(
            str(origin.automation_id),
            project_root=ROOT,
            environ={"CODEX_THREAD_ID": evidence["session_id"]},
        )
        if isinstance(envelope, imports.ScheduledImportEnvelope):
            scheduled_origin = envelope.scheduled_origin
            started = datetime.fromisoformat(actual["executed_at"])
            return (
                actual["execution_mode"] == "scheduled"
                and actual["occurrence_id"] == scheduled_origin.occurrence_id
                and started <= scheduled_origin.executed_at <= started + timedelta(hours=6)
            )
        return bool(
            actual["execution_mode"] == "manual"
            and actual["manual_run_id"] == envelope.manual_origin.manual_run_id
            and actual["session_id"] == str(envelope.manual_origin.session_id)
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    staged = path.parent / (uuid4().hex + ".part")
    try:
        with staged.open("xb") as out:
            out.write(canonical(value))
            out.flush()
            os.fsync(out.fileno())
        # Exclusive publication, also on POSIX; never overwrite another run.
        os.link(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def save_pending(
    root: Path,
    raw: bytes,
    target_blog_id: str | None = None,
    invocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not 0 < len(raw) <= 262144:
        raise ValueError("pending_envelope_size_invalid")
    envelope = validate_envelope(raw)
    key = pending_key(envelope, target_blog_id)
    directories = _safe_directories(root)
    digest = hashlib.sha256(raw).hexdigest()
    mode, run, blog = identity(envelope, target_blog_id)
    origin = (
        envelope.scheduled_origin
        if isinstance(envelope, imports.ScheduledImportEnvelope)
        else envelope.manual_origin
    )
    value: dict[str, Any] = {
        "schema": "woori-pending-manuscript/1.0",
        "idempotency_key": key,
        "status": "import_pending",
        "writing_status": "manuscript_saved",
        "duplicate_status": "pending",
        "import_status": "pending",
        "hold_reason": "duplicate_check_unavailable",
        "execution_mode": mode,
        "automation_id": origin.automation_id,
        "run_id": run,
        "scheduled_slot": getattr(origin, "scheduled_slot", None),
        "occurrence_id_source": getattr(origin, "occurrence_id_source", None),
        "scheduler_occurrence_id": getattr(origin, "scheduler_occurrence_id", None),
        "topic": envelope.item.title,
        "target_blog_id": blog,
        "saved_at": datetime.now(UTC).isoformat(),
        "manuscript_sha256": digest,
        # Preserve exact raw bytes for unchanged retries and provenance.
        "manuscript_utf8": raw.decode("utf-8"),
        "invocation_evidence": invocation,
    }
    value["scheduled_slot"] = (
        value["scheduled_slot"].isoformat() if value["scheduled_slot"] else None
    )
    target = directories["pending"] / (key + ".pending.json")
    if target.exists():
        if _is_reparse_point(target):
            raise ValueError("pending_occurrence_payload_conflict")
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("manuscript_sha256") != digest:
            raise ValueError("pending_occurrence_payload_conflict")
        value = existing
    else:
        try:
            _exclusive_json(target, value)
        except FileExistsError:
            return save_pending(root, raw, target_blog_id, invocation)
    return {k: v for k, v in value.items() if k != "manuscript_utf8"} | {"path": str(target)}


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manuscript_utf8: str = Field(min_length=1, max_length=262144)
    manuscript_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_blog_id: str | None = None
    invocation_evidence: dict[str, Any] | None = None


@router.post("/admin/research/content-imports/scheduled-recovery")
def recover_manuscript(request: RecoveryRequest) -> dict[str, Any]:
    raw = request.manuscript_utf8.encode("utf-8")
    if not 0 < len(raw) <= 262144 or hashlib.sha256(raw).hexdigest() != request.manuscript_sha256:
        raise HTTPException(422, "pending_payload_hash_or_size_invalid")
    try:
        envelope = validate_envelope(raw)
        mode, run, blog = identity(envelope, request.target_blog_id)
        key = pending_key(envelope, request.target_blog_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "pending_identity_or_envelope_invalid") from exc
    origin = (
        envelope.scheduled_origin
        if isinstance(envelope, imports.ScheduledImportEnvelope)
        else envelope.manual_origin
    )
    with connection() as conn:
        # Serialize one occurrence, then matching target/event across occurrences.
        for lock in sorted(
            ["pending:" + key, f"scheduled-event:{blog}:{envelope.item.event_group_id}"]
        ):
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock,))
        prior = conn.execute(
            """SELECT payload FROM audit_events
            WHERE event_type='scheduled_pending.outcome' AND payload->>'idempotency_key'=%s
            ORDER BY id DESC LIMIT 1""",
            (key,),
        ).fetchone()
        if prior:
            if prior["payload"]["manuscript_sha256"] != request.manuscript_sha256:
                raise HTTPException(409, "pending_occurrence_payload_conflict")
            return cast(dict[str, Any], prior["payload"])

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            result.update(
                {
                    "idempotency_key": key,
                    "manuscript_sha256": request.manuscript_sha256,
                    "automation_id": origin.automation_id,
                    "execution_mode": mode,
                    "run_id": run,
                    "publish_ready": False,
                    "blogger_writes": 0,
                }
            )
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES('scheduled_pending.outcome',%s)",
                (Jsonb(result),),
            )
            return result

        field = "occurrence_id" if mode == "scheduled" else "manual_run_id"
        event = (
            "content.import.scheduled_origin_recorded"
            if mode == "scheduled"
            else "content.import.manual_automation_origin_recorded"
        )
        existing = conn.execute(
            "SELECT payload FROM audit_events WHERE event_type=%s AND payload->>%s=%s LIMIT 1",
            (event, field, run),
        ).fetchone()
        if existing:
            return finish(
                {
                    "status": "duplicate_skipped",
                    "reason": "occurrence_already_imported",
                    "import_id": existing["payload"].get("import_id"),
                }
            )
        invocation_evidence = request.invocation_evidence
        # Rolling upgrade: an older intake process sends only bytes/hash. Read
        # evidence from the exact immutable pending record, never from a URL or
        # arbitrary caller path; then revalidate the real Desktop transcript.
        if invocation_evidence is None:
            directories = _safe_directories(ROOT / ".local/gpt-scheduled-import")
            saved_path = directories["pending"] / (key + ".pending.json")
            try:
                if not _is_reparse_point(saved_path) and saved_path.stat().st_size <= 1048576:
                    saved = json.loads(saved_path.read_text(encoding="utf-8"))
                    if (
                        saved.get("manuscript_sha256") == request.manuscript_sha256
                        and saved.get("manuscript_utf8") == request.manuscript_utf8
                    ):
                        invocation_evidence = saved.get("invocation_evidence")
            except (OSError, ValueError):
                pass
        if not verify_saved_invocation(envelope, invocation_evidence):
            return finish({"status": "review_required", "reason": "actual_invocation_unverified"})
        now = datetime.now(UTC)
        source_time = (
            envelope.scheduled_origin.source_as_of
            if isinstance(envelope, imports.ScheduledImportEnvelope)
            else envelope.item.fact_checked_at
        )
        if any(
            value is None or value > now + timedelta(minutes=5) or now - value > MAX_AGE
            for value in (envelope.item.generated_at, source_time)
        ):
            return finish(
                {
                    "status": "review_required",
                    "reason": "stale_or_future_manuscript_requires_fresh_research",
                }
            )
        from .editorial_quality import evaluate

        item_data = envelope.item.model_dump(mode="json")
        quality = evaluate({**item_data, "seo_metadata": item_data["seo"]}, item_data)
        if not quality.get("checks", {}).get("safe_html", False):
            return finish({"status": "review_required", "reason": "unsafe_manuscript"})
        duplicate = imports._scheduled_duplicate_check(
            imports.DuplicateCheckRequest(
                language_code=envelope.item.language_code,
                target_country=envelope.item.source_region,
                target_blog_id=blog,
                event_group_id=envelope.item.event_group_id,
                topic=envelope.item.title,
                content_id=envelope.item.content_id,
                trade_date=getattr(origin, "market_date", None),
                stage="generation",
            ),
            conn,
        )
        if duplicate.get("local_status") in {"already_imported", "already_published"}:
            return finish(
                {
                    "status": "duplicate_skipped",
                    "reason": duplicate["reason"],
                    "import_id": duplicate.get("import_id"),
                    "content_version_id": duplicate.get("content_version_id"),
                }
            )
        if duplicate.get("draft_import_allowed") is not True:
            return {"status": "import_pending", "reason": "duplicate_check_unavailable"}
        submission = imports.ImportSubmission(
            submitted_by=envelope.submitted_by,
            item=envelope.item,
            manual_automation_origin=envelope.manual_origin
            if isinstance(envelope, imports.ManualAutomationImportEnvelope)
            else None,
        )
        result = imports._submit_content_import(submission, conn)
        if isinstance(envelope, imports.ScheduledImportEnvelope):
            imports._record_scheduled_import_origin(
                UUID(result["import_id"]), envelope.scheduled_origin, conn
            )
        return finish(
            {
                "status": "imported",
                "import_id": result["import_id"],
                "content_version_id": result["content_version_id"],
                "duplicate": result.get("duplicate", False),
                "recovery_duplicate_check": duplicate,
            }
        )


def recover_pending_once(
    root: Path, client: httpx.Client, *, max_files: int = 4
) -> list[dict[str, Any]]:
    directories = _safe_directories(root)
    results: list[dict[str, Any]] = []
    for file in sorted(directories["pending"].glob("*.pending.json")):
        receipt = directories["pending_receipts"] / file.name
        if receipt.exists():
            continue
        if len(results) >= max_files:
            break
        if _is_reparse_point(file) or file.stat().st_size > 2 * 262144:
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            response = client.post(
                "/admin/research/content-imports/scheduled-recovery",
                json={
                    "manuscript_utf8": data["manuscript_utf8"],
                    "manuscript_sha256": data["manuscript_sha256"],
                    "target_blog_id": data["target_blog_id"],
                    "invocation_evidence": data.get("invocation_evidence"),
                },
            )
            result = (
                response.json()
                if response.status_code == 200
                else {
                    "status": "import_pending",
                    "reason": "recovery_api_unavailable",
                    "http_status": response.status_code,
                }
            )
            if result.get("status") in {"imported", "duplicate_skipped", "review_required"}:
                try:
                    _exclusive_json(receipt, result)
                except FileExistsError:
                    pass
            results.append({"file_key": file.stem, **result})
        except (OSError, ValueError, KeyError):
            results.append(
                {
                    "file_key": file.stem,
                    "status": "import_pending",
                    "reason": "pending_record_unavailable",
                }
            )
        except httpx.HTTPError:
            results.append(
                {
                    "file_key": file.stem,
                    "status": "import_pending",
                    "reason": "recovery_api_unavailable",
                }
            )
    return results


def record_progress(root: Path, invocation: dict[str, Any], status: str) -> dict[str, Any]:
    if status not in {
        "scheduled",
        "duplicate_check_running",
        "researching",
        "writing",
        "usage_limit_waiting",
        "failed",
    }:
        raise ValueError("unsupported_progress_state")
    run_id = invocation.get("occurrence_id") or invocation.get("manual_run_id")
    if not run_id or invocation.get("execution_mode") not in {"scheduled", "manual"}:
        raise ValueError("verified_invocation_required")
    directories = _safe_directories(root)
    if status == "failed":
        for file in directories["pending"].glob("*.pending.json"):
            if (
                not _is_reparse_point(file)
                and json.loads(file.read_text(encoding="utf-8")).get("run_id") == run_id
            ):
                status = "import_pending"
                break
    value = {
        "id": uuid4().hex,
        "status": status,
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "automation_id": invocation["automation_id"],
        "execution_mode": invocation["execution_mode"],
        "scheduled_slot": invocation.get("scheduled_slot"),
        "occurrence_id_source": invocation.get("occurrence_id_source"),
        "scheduler_occurrence_id": invocation.get("scheduler_occurrence_id"),
        "self_reported_progress": True,
        "blogger_writes": 0,
    }
    _exclusive_json(directories["progress"] / (str(value["id"]) + ".json"), value)
    return value


class ProgressRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    status: Literal[
        "scheduled",
        "duplicate_check_running",
        "researching",
        "writing",
        "manuscript_saved",
        "import_pending",
        "imported",
        "duplicate_skipped",
        "usage_limit_waiting",
        "failed",
    ]
    recorded_at: datetime
    run_id: str = Field(min_length=8, max_length=180)
    automation_id: str = Field(min_length=1, max_length=128)
    execution_mode: Literal["scheduled", "manual"]
    scheduled_slot: str | None
    occurrence_id_source: str | None
    scheduler_occurrence_id: str | None
    self_reported_progress: Literal[True]
    blogger_writes: Literal[0]


@router.post("/admin/research/scheduled-manuscripts/progress")
def sync_progress(request: ProgressRecord) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    with connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("progress:" + digest,)
        )
        prior = conn.execute(
            "SELECT id FROM audit_events WHERE event_type='scheduled_pending.progress' AND payload->>'record_hash'=%s",
            (digest,),
        ).fetchone()
        if prior:
            return {"audit_id": prior["id"], "duplicate": True}
        row = conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES('scheduled_pending.progress',%s) RETURNING id",
            (Jsonb({**payload, "record_hash": digest}),),
        ).fetchone()
        return {"audit_id": row["id"] if row else None, "duplicate": False}


def sync_progress_once(root: Path, client: httpx.Client) -> None:
    directories = _safe_directories(root)
    files = [
        file
        for file in sorted(directories["progress"].glob("*.json"))
        if not (directories["progress_receipts"] / file.name).exists()
    ][:100]
    for file in files:
        receipt = directories["progress_receipts"] / file.name
        if _is_reparse_point(file) or file.stat().st_size > 8192:
            continue
        try:
            response = client.post(
                "/admin/research/scheduled-manuscripts/progress",
                json=json.loads(file.read_text(encoding="utf-8")),
            )
            if response.status_code == 200:
                _exclusive_json(receipt, response.json())
        except (OSError, ValueError, httpx.HTTPError):
            continue
