"""Fail-closed, one-shot intake for user-authorized ChatGPT Work exports."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import TypeAdapter, ValidationError

from .content_imports import ManualAutomationImportEnvelope, ScheduledImportEnvelope

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "api"))

MAX_FILE_BYTES = 256 * 1024
DEFAULT_MAX_FILES = 4
IMPORT_PATH = "/admin/research/content-imports"
_SECRETISH = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/-]+=*|([?&](?:access_token|token|code|key)=)[^&\s]+|"
    r"(\b(?:access_token|refresh_token|token|password|client_secret|api_key)\s*[:=]\s*)[^\s,;]+|"
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


def _safe_error_text(value: object, *, limit: int = 500) -> str:
    """Keep useful API/Pydantic diagnostics while excluding secrets and PII."""
    text = " ".join(str(value).split())
    if re.search(r"(?i)\b(?:secret|credential|authorization|cookie|password)\b", text):
        return "sensitive_api_error_omitted"
    text = _SECRETISH.sub(
        lambda match: (match.group(1) or match.group(2) or match.group(3) or "") + "[redacted]", text
    )
    return text[:limit]


def _safe_validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "location": ".".join(str(part) for part in entry.get("loc", ()))[:160],
            "type": _safe_error_text(entry.get("type", "validation_error"), limit=80),
            "message": _safe_error_text(entry.get("msg", "Invalid value"), limit=240),
        }
        for entry in error.errors(include_input=False)[:8]
    ]


def _safe_api_error(response: httpx.Response) -> str | None:
    """Extract only a bounded JSON detail; never retain headers or raw bodies."""
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, (str, int, float)):
        return _safe_error_text(detail)
    if isinstance(detail, list):
        parts = []
        for entry in detail[:5]:
            if isinstance(entry, dict):
                location = ".".join(str(part) for part in entry.get("loc", ()))
                message = entry.get("msg", "Invalid request")
                parts.append(f"{location}: {message}" if location else str(message))
            else:
                parts.append(str(entry))
        return _safe_error_text("; ".join(parts)) if parts else None
    return None


ImportEnvelope = ScheduledImportEnvelope | ManualAutomationImportEnvelope
_ENVELOPE_ADAPTER: TypeAdapter[ImportEnvelope] = TypeAdapter(cast(Any, ImportEnvelope))


def validate_envelope(raw: bytes) -> ImportEnvelope:
    """Validate either a real scheduled export or explicit Desktop Run now envelope."""
    return _ENVELOPE_ADAPTER.validate_json(raw)


def _loopback_api_url(value: str) -> str:
    parts = urlsplit(value)
    host = parts.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if (
        parts.scheme != "http" or not loopback or parts.username or parts.password
        or not parts.port or parts.path not in ("", "/") or parts.query or parts.fragment
    ):
        raise ValueError("inbox_api_must_be_an_explicit_loopback_http_origin")
    return value.rstrip("/")


def _safe_directories(root: Path) -> dict[str, Path]:
    expected_root = PROJECT_ROOT / ".local" / "gpt-scheduled-import"
    if root.absolute() == expected_root.absolute():
        local_root = root.parent
        local_root.mkdir(parents=True, exist_ok=True)
        if _is_reparse_point(local_root) or local_root.resolve(strict=True).parent != PROJECT_ROOT.resolve(strict=True):
            raise ValueError("inbox_local_parent_must_not_be_a_symlink_or_junction")
    root.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(root):
        raise ValueError("inbox_root_must_not_be_a_symlink")
    resolved_root = root.resolve(strict=True)
    directories: dict[str, Path] = {}
    for name in ("incoming", "ready", "processing", "processed", "rejected", "failed", "quarantine"):
        path = root / name
        path.mkdir(exist_ok=True)
        if _is_reparse_point(path) or path.resolve(strict=True).parent != resolved_root:
            raise ValueError("inbox_state_directory_must_be_a_direct_child")
        directories[name] = path
    return directories


def _file_key(path: Path) -> str:
    return hashlib.sha256(path.name.encode("utf-8", errors="replace")).hexdigest()[:16]


def _is_reparse_point(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (bool(is_junction()) if is_junction else False)


def _move(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError("inbox_destination_exists")
    source.replace(target)


def _recover_interrupted(directories: dict[str, Path], *, stale_after_seconds: int = 300) -> int:
    recovered = 0
    now = time.time()
    for entry in sorted(directories["processing"].glob("*.processing.json")):
        if _is_reparse_point(entry) or not entry.is_file():
            continue
        try:
            if now - entry.stat().st_mtime < stale_after_seconds:
                continue
        except OSError:
            continue
        ready_name = entry.name.removesuffix(".processing.json") + ".ready.json"
        target = directories["ready"] / ready_name
        if not target.exists():
            _move(entry, target)
            recovered += 1
    return recovered


def retry_quarantined_file(root: Path, filename: str) -> dict[str, Any]:
    """Audited, fail-closed requeue for a previously quarantined scheduled export.

    The exact quarantine file is moved (never copied or rewritten) only when its
    checksum matches an earlier invalid-envelope outcome and no import/origin
    record already exists. The normal inbox worker then performs the import.
    """
    from psycopg.types.json import Jsonb

    from .db import connection

    if Path(filename).name != filename or not filename.endswith(".processing.json"):
        raise ValueError("quarantine_retry_requires_exact_processing_filename")
    directories = _safe_directories(root)
    source = directories["quarantine"] / filename
    if _is_reparse_point(source) or not source.is_file():
        raise FileNotFoundError("quarantined_file_not_found_or_unsafe")
    size = source.stat().st_size
    if size <= 0 or size > MAX_FILE_BYTES:
        raise ValueError("quarantined_file_size_invalid")
    raw = source.read_bytes()
    file_sha256 = hashlib.sha256(raw).hexdigest()
    envelope = validate_envelope(raw)
    file_key = _file_key(Path(filename.removesuffix(".processing.json") + ".ready.json"))
    target_name = filename.removesuffix(".processing.json") + ".ready.json"
    target = directories["ready"] / target_name
    if target.exists():
        raise FileExistsError("quarantine_retry_ready_destination_exists")

    with connection() as conn:
        prior = conn.execute(
            """SELECT id,payload FROM audit_events
            WHERE event_type='scheduled_import.file_outcome'
              AND payload->>'file_sha256'=%s
              AND payload->>'file_key'=%s
              AND payload->>'status'='quarantined'
              AND payload->>'reason'='invalid_envelope'
            ORDER BY id DESC LIMIT 1""",
            (file_sha256, file_key),
        ).fetchone()
        if not prior:
            raise ValueError("matching_quarantine_audit_not_found")
        imported = conn.execute(
            "SELECT id FROM external_content_imports WHERE external_content_id=%s LIMIT 1",
            (envelope.item.content_id,),
        ).fetchone()
        if imported:
            raise ValueError("content_already_imported_retry_refused")
        if isinstance(envelope, ScheduledImportEnvelope):
            origin_lookup = conn.execute(
                """SELECT id FROM audit_events
                WHERE event_type='content.import.scheduled_origin_recorded'
                  AND payload->>'occurrence_id'=%s LIMIT 1""",
                (envelope.scheduled_origin.occurrence_id,),
            ).fetchone()
            origin_id_field = {"occurrence_id": envelope.scheduled_origin.occurrence_id}
        else:
            origin_lookup = conn.execute(
                """SELECT id FROM audit_events
                WHERE event_type='content.import.manual_automation_origin_recorded'
                  AND payload->>'manual_run_id'=%s LIMIT 1""",
                (envelope.manual_origin.manual_run_id,),
            ).fetchone()
            origin_id_field = {"manual_run_id": envelope.manual_origin.manual_run_id}
        if origin_lookup:
            raise ValueError("automation_run_already_recorded_retry_refused")
        conn.execute(
            """INSERT INTO audit_events(event_type,language_code,payload)
            VALUES ('scheduled_import.quarantine_retry_requested',%s,%s)""",
            (envelope.item.language_code, Jsonb({
                "file_key": file_key,
                "file_sha256": file_sha256,
                "original_quarantine_file": filename,
                "ready_file": target_name,
                "prior_outcome_event_id": prior["id"],
                "content_id": envelope.item.content_id,
                "execution_mode": "scheduled" if isinstance(envelope, ScheduledImportEnvelope) else "manual",
                **origin_id_field,
                "reason": "retry_after_worker_schema_refresh",
                "blogger_writes": 0,
            })),
        )
    # Commit the retry audit before the file becomes visible to the running
    # Worker. If the move fails, the quarantine file remains available for an
    # explicit retry and the append-only request event is still truthful.
    _move(source, target)
    return {
        "status": "requeued",
        "file_key": file_key,
        "file_sha256": file_sha256,
        "prior_outcome_event_id": prior["id"],
        "content_id": envelope.item.content_id,
        "execution_mode": "scheduled" if isinstance(envelope, ScheduledImportEnvelope) else "manual",
        **origin_id_field,
        "ready_file": str(target),
        "blogger_writes": 0,
    }


def process_inbox_once(
    root: Path,
    api_base_url: str,
    admin_token: str,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    transport: httpx.BaseTransport | None = None,
    operations_target_confirmed: bool = False,
) -> dict[str, Any]:
    """Submit at most ``max_files`` complete .ready.json files to a loopback API.

    A submission is always imported as review-held content. The separate origin
    audit request is idempotent, so interrupted runs can safely resume via the
    API's existing content idempotency and this endpoint's occurrence key.
    """
    if not 1 <= max_files <= 4:
        raise ValueError("inbox_file_limit_must_be_between_1_and_4")
    if not admin_token or len(admin_token) < 32:
        raise ValueError("inbox_admin_token_unavailable")
    base_url = _loopback_api_url(api_base_url)
    port = urlsplit(base_url).port
    if port == 8100 and not operations_target_confirmed:
        raise ValueError("operations_api_requires_explicit_confirmation")
    directories = _safe_directories(root)
    recovered = _recover_interrupted(directories)
    headers = {"Authorization": f"Bearer {admin_token}"}
    results: list[dict[str, Any]] = []
    file_hashes: dict[str, str] = {}

    with httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(10.0, connect=2.0),
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    ) as client:
        ready_files = sorted(directories["ready"].glob("*.ready.json"))[:max_files]
        for source in ready_files:
            file_key = _file_key(source)
            if _is_reparse_point(source) or not source.is_file():
                results.append({"file_key": file_key, "status": "ignored_unsafe_path"})
                continue
            processing = directories["processing"] / (
                source.name.removesuffix(".ready.json") + ".processing.json"
            )
            try:
                _move(source, processing)
            except OSError:
                results.append({"file_key": file_key, "status": "not_claimed"})
                continue
            try:
                size = processing.stat().st_size
                if size <= 0 or size > MAX_FILE_BYTES:
                    _move(processing, directories["quarantine"] / processing.name)
                    results.append({"file_key": file_key, "status": "quarantined", "reason": "invalid_file_size"})
                    continue
                raw = processing.read_bytes()
                file_sha256 = hashlib.sha256(raw).hexdigest()
                file_hashes[file_key] = file_sha256
                envelope = validate_envelope(raw)
            except ValidationError as exc:
                validation_errors = _safe_validation_errors(exc)
                try:
                    _move(processing, directories["quarantine"] / processing.name)
                except OSError:
                    pass
                results.append({"file_key": file_key, "status": "quarantined", "reason": "invalid_envelope",
                                "http_status": None, "validation_errors": validation_errors})
                continue
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                try:
                    _move(processing, directories["quarantine"] / processing.name)
                except OSError:
                    pass
                results.append({"file_key": file_key, "status": "quarantined", "reason": "invalid_envelope",
                                "http_status": None, "api_error": _safe_error_text(exc)})
                continue

            submission: dict[str, Any] = {
                "submitted_by": envelope.submitted_by,
                "item": envelope.item.model_dump(mode="json", exclude_none=False),
            }
            if isinstance(envelope, ManualAutomationImportEnvelope):
                submission["manual_automation_origin"] = envelope.manual_origin.model_copy(update={
                    "inbox_file_name": source.name,
                    "inbox_file_sha256": file_sha256,
                }).model_dump(mode="json", exclude_none=False)
            try:
                imported = client.post(IMPORT_PATH, json=submission)
                if imported.status_code not in (200, 201):
                    category = "api_rejected" if imported.status_code < 500 else "api_unavailable"
                    target = "rejected" if imported.status_code < 500 else "ready"
                    destination = directories[target] / (
                        source.name if target == "ready" else processing.name
                    )
                    _move(processing, destination)
                    results.append({"file_key": file_key, "status": target, "reason": category,
                                    "http_status": imported.status_code,
                                    "api_error": _safe_api_error(imported),
                                    "file_sha256": file_sha256})
                    continue
                import_result = imported.json()
                import_id = str(import_result.get("import_id", ""))
                if not import_id:
                    _move(processing, directories["ready"] / source.name)
                    results.append({"file_key": file_key, "status": "ready", "reason": "api_receipt_missing"})
                    continue
                if isinstance(envelope, ScheduledImportEnvelope):
                    origin = client.post(
                        f"{IMPORT_PATH}/{import_id}/scheduled-origin",
                        json=envelope.scheduled_origin.model_copy(update={
                            "inbox_file_name": source.name,
                            "inbox_file_sha256": file_sha256,
                        }).model_dump(mode="json", exclude_none=False),
                    )
                    if origin.status_code not in (200, 201):
                        retry_target = "ready" if origin.status_code >= 500 else "rejected"
                        retry_name = source.name if retry_target == "ready" else processing.name
                        _move(processing, directories[retry_target] / retry_name)
                        results.append({"file_key": file_key, "status": retry_target, "reason": "origin_audit_pending",
                                        "http_status": origin.status_code, "api_error": _safe_api_error(origin)})
                        continue
                    receipt = origin.json()
                    origin_audit_event_id = receipt.get("audit_event_id")
                else:
                    receipt = import_result
                    origin_audit_event_id = import_result.get("manual_automation_audit_event_id")
                    if not origin_audit_event_id:
                        _move(processing, directories["ready"] / source.name)
                        results.append({"file_key": file_key, "status": "ready", "reason": "manual_origin_audit_pending"})
                        continue
                source_capture: dict[str, Any] = {"status": "not_run"}
                try:
                    captured = client.post(f"{IMPORT_PATH}/{import_id}/live-source-evidence")
                    if captured.status_code in (200, 201):
                        source_capture = {"status": "recorded", **captured.json()}
                    else:
                        source_capture = {"status": "unavailable", "http_status": captured.status_code,
                                          "api_error": _safe_api_error(captured)}
                except (httpx.HTTPError, json.JSONDecodeError) as exc:
                    source_capture = {"status": "unavailable", "reason": _safe_error_text(exc)}
                detail = client.get(f"{IMPORT_PATH}/{import_id}")
                if detail.status_code != 200:
                    retry_target = "ready" if detail.status_code >= 500 else "rejected"
                    retry_name = source.name if retry_target == "ready" else processing.name
                    _move(processing, directories[retry_target] / retry_name)
                    results.append({"file_key": file_key, "status": retry_target,
                                    "reason": "assessment_state_unavailable",
                                    "http_status": detail.status_code, "api_error": _safe_api_error(detail)})
                    continue
                detail_data = detail.json()
                latest_version = detail_data.get("latest_version") or {}
                version_id = str(latest_version.get("id", ""))
                assessments = detail_data.get("assessments") or []
                assessment = next(
                    (entry for entry in assessments if str(entry.get("version_id")) == version_id),
                    None,
                )
                if not assessment:
                    if not version_id:
                        _move(processing, directories["rejected"] / processing.name)
                        results.append({"file_key": file_key, "status": "rejected",
                                        "reason": "import_version_missing"})
                        continue
                    assessed = client.post(
                        f"{IMPORT_PATH}/{import_id}/assessment", json={"version_id": version_id}
                    )
                    if assessed.status_code not in (200, 201):
                        retry_target = "ready" if assessed.status_code >= 500 else "rejected"
                        retry_name = source.name if retry_target == "ready" else processing.name
                        _move(processing, directories[retry_target] / retry_name)
                        results.append({"file_key": file_key, "status": retry_target,
                                        "reason": "machine_assessment_failed",
                                        "http_status": assessed.status_code, "api_error": _safe_api_error(assessed)})
                        continue
                    assessment = assessed.json()
                _move(processing, directories["processed"] / processing.name)
                results.append({
                    "file_key": file_key,
                    "file_sha256": file_sha256,
                    "status": "imported",
                    "import_id": import_id,
                    "audit_event_id": origin_audit_event_id,
                    "duplicate": bool(import_result.get("duplicate")),
                    "machine_assessment_passed": bool(assessment.get("machine_passed")),
                    "independent_source_verification": bool(assessment.get("independent_source_verification")),
                    "execution_mode": "scheduled" if isinstance(envelope, ScheduledImportEnvelope) else "manual",
                    "automation_id": (
                        envelope.scheduled_origin.automation_id if isinstance(envelope, ScheduledImportEnvelope)
                        else envelope.manual_origin.automation_id
                    ),
                    "automation_run_id": (
                        envelope.scheduled_origin.occurrence_id if isinstance(envelope, ScheduledImportEnvelope)
                        else envelope.manual_origin.manual_run_id
                    ),
                    "source_evidence_capture": source_capture,
                    "provenance_verified": False,
                    "generation_ready": False,
                    "publish_ready": False,
                    "blogger_write_performed": False,
                })
            except (httpx.HTTPError, json.JSONDecodeError):
                if processing.exists():
                    try:
                        _move(processing, directories["ready"] / source.name)
                    except OSError:
                        pass
                results.append({"file_key": file_key, "status": "ready", "reason": "local_api_unavailable"})
            except OSError:
                # Preserve uncertain work in processing; the next invocation requeues
                # it, and both API operations are idempotent.
                results.append({"file_key": file_key, "status": "processing", "reason": "filesystem_transition_failed"})

    for result in results:
        result.setdefault("file_sha256", file_hashes.get(str(result.get("file_key", ""))))
    return {"recovered_processing_files": recovered, "processed_count": len(results), "results": results,
            "external_ai_calls": 0, "blogger_writes": 0, "auto_publication_enabled": False}


def main() -> None:
    import argparse

    from woori.config import settings

    project_root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description="Import complete, user-reviewed scheduled Work export files")
    parser.add_argument("--operations", action="store_true", help="Target the local operations API on port 8100")
    parser.add_argument("--confirm-operations-import", action="store_true", help="Confirm that review-held content will be written to the operations DB")
    parser.add_argument("--retry-quarantined", metavar="FILENAME", help="Audited requeue of one exact quarantine processing filename")
    args = parser.parse_args()
    os.chdir(project_root)
    if args.operations != args.confirm_operations_import:
        raise SystemExit("Operations import requires both --operations and --confirm-operations-import")
    inbox = project_root / ".local" / "gpt-scheduled-import"
    if _is_reparse_point(project_root / ".local") or _is_reparse_point(inbox):
        raise SystemExit("Scheduled import inbox must not use a symlink or junction")
    if args.retry_quarantined:
        try:
            result = retry_quarantined_file(inbox, args.retry_quarantined)
        except (ValueError, OSError) as exc:
            raise SystemExit(str(exc)) from None
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return
    url = "http://127.0.0.1:8100" if args.operations else "http://127.0.0.1:18100"
    try:
        result = process_inbox_once(
            inbox, url, settings().admin_token,
            operations_target_confirmed=args.operations and args.confirm_operations_import,
        )
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
