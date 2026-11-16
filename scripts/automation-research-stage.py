"""Run one verified Desktop Automation preflight and live-research stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_DIR = ROOT / ".local" / "gpt-scheduled-import" / "preflight"
PACKAGE_DIR = ROOT / ".local" / "gpt-scheduled-import" / "research-packages"
MAX_PREFLIGHT_BYTES = 128_000
MAX_BROKER_BYTES = 256_000


def _json_object(raw: str, *, limit: int, failure: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > limit:
        raise ValueError(failure)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError(failure)
    return value


def _identity(preflight: dict[str, Any], automation_id: str) -> tuple[str, str, dict[str, Any]]:
    execution = preflight.get("automation_execution")
    if not isinstance(execution, dict) or execution.get("contract_error"):
        raise ValueError("authoring_contract_unavailable")
    invocation = execution.get("invocation")
    contract = execution.get("contract")
    if not isinstance(invocation, dict) or not isinstance(contract, dict):
        raise TypeError("authoring_contract_unavailable")
    if invocation.get("automation_id") != automation_id:
        raise ValueError("automation_identity_mismatch")
    mode = invocation.get("execution_mode")
    if mode == "scheduled":
        identity = invocation.get("occurrence_id")
        if not isinstance(identity, str) or not re.fullmatch(
            rf"codex-slot:{re.escape(automation_id)}:\d{{8}}T\d{{4}}KST", identity
        ):
            raise ValueError("scheduled_occurrence_identity_invalid")
    elif mode == "manual":
        identity = invocation.get("manual_run_id")
        if invocation.get("trigger") != "automation_cron_run_now":
            raise ValueError("manual_run_now_trigger_required")
        if not isinstance(identity, str) or not re.fullmatch(
            rf"codex-manual:{re.escape(automation_id)}:[0-9a-fA-F-]{{36}}", identity
        ):
            raise ValueError("manual_run_identity_invalid")
    else:
        raise ValueError("unsupported_execution_mode")
    if not isinstance(identity, str) or not identity:
        raise ValueError("execution_identity_missing")
    if preflight.get("local_status") not in {"not_found", "failed_only"}:
        raise ValueError("local_duplicate_preflight_not_clear")
    if preflight.get("draft_import_allowed") is not True:
        raise ValueError("draft_import_not_allowed")
    return mode, identity, invocation


def _preflight_path(mode: str, identity: str, *, directory: Path) -> Path:
    digest = hashlib.sha256(f"{mode}:{identity}".encode()).hexdigest()[:32]
    return directory / f"{digest}.generation-preflight.json"


def _package_path(mode: str, identity: str, automation_id: str, *, directory: Path) -> Path:
    if mode == "scheduled":
        suffix = identity.rsplit(":", 1)[-1]
        if not re.fullmatch(r"\d{8}T\d{4}KST", suffix):
            raise ValueError("scheduled_occurrence_invalid")
        name = f"{automation_id}-{suffix}.research.json"
    else:
        match = re.fullmatch(r"codex-manual:([A-Za-z0-9_-]{1,80}):([0-9a-fA-F-]{36})", identity)
        if match is None or match.group(1) != automation_id:
            raise ValueError("manual_run_identity_invalid")
        name = f"{automation_id}-manual-{match.group(2).lower()}.research.json"
    return directory / name


def _write_immutable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        with staging.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory rename is atomic on the project volume and fails if
        # the identity-bound destination already exists on Windows.
        os.rename(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _result(
    *, status: str, reason: str | None = None, mode: str | None = None,
    identity: str | None = None, preflight: dict[str, Any] | None = None,
    preflight_path: Path | None = None, research_path: Path | None = None,
    source_count: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if reason:
        result["reason"] = reason[:160]
    if mode:
        result["execution_mode"] = mode
    if identity:
        result["run_identity"] = identity
    if preflight is not None:
        result.update({
            "local_status": preflight.get("local_status"),
            "remote_status": preflight.get("remote_status", "not_checked"),
            "overall_status": preflight.get("status", "unknown"),
            "draft_import_allowed": preflight.get("draft_import_allowed") is True,
        })
    if preflight_path:
        result["preflight_json_path"] = str(preflight_path)
    if research_path:
        result["research_package_path"] = str(research_path)
    if source_count is not None:
        result["source_count"] = source_count
    result["article_created"] = False
    result["imported"] = False
    result["published"] = False
    return result


def run_stage(
    *, automation_id: str, category: str, language_code: str,
    target_country: str, target_blog_id: str, event_group_id: str, topic: str,
    root: Path = ROOT, preflight_dir: Path | None = None,
    package_dir: Path | None = None, command_runner=subprocess.run,
) -> tuple[dict[str, Any], int]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", automation_id):
        return _result(status="blocked", reason="automation_id_invalid"), 2
    for name, value in (("topic", topic), ("event_group_id", event_group_id),
                        ("language_code", language_code), ("target_country", target_country),
                        ("target_blog_id", target_blog_id)):
        if not isinstance(value, str) or not value.strip():
            return _result(status="blocked", reason=f"{name}_missing"), 2
    if not re.fullmatch(r"[0-9]{5,32}", target_blog_id):
        return _result(status="blocked", reason="target_blog_id_invalid"), 2

    python = sys.executable
    duplicate_command = [
        python, str(root / "scripts" / "scheduled_duplicate_check.py"),
        "--stage", "generation", "--automation-id", automation_id,
        "--language-code", language_code, "--target-country", target_country,
        "--target-blog-id", target_blog_id, "--event-group-id", event_group_id,
        "--topic", topic,
    ]
    preflight: dict[str, Any] | None = None
    try:
        checked = command_runner(
            duplicate_command, cwd=root, capture_output=True, text=True,
            encoding="utf-8", timeout=360, check=False,
        )
        preflight_text = checked.stdout
        preflight = _json_object(
            preflight_text, limit=MAX_PREFLIGHT_BYTES,
            failure="generation_preflight_invalid",
        )
        if checked.returncode != 0:
            reason = preflight.get("reason")
            return _result(
                status="blocked",
                reason=reason if isinstance(reason, str) else "generation_preflight_failed",
                preflight=preflight,
            ), 3
        mode, identity, _invocation = _identity(preflight, automation_id)
        if mode == "scheduled":
            # Bind this occurrence to every resolved task input used by the
            # generation preflight. A retry may reuse evidence only for the
            # exact same scheduled request.
            preflight["scheduled_request"] = {
                "automation_id": automation_id,
                "category": category,
                "language_code": language_code,
                "target_country": target_country,
                "target_blog_id": target_blog_id,
                "event_group_id": event_group_id,
                "topic": topic,
            }
            preflight_text = json.dumps(preflight, ensure_ascii=True, sort_keys=True)
    except subprocess.TimeoutExpired:
        return _result(status="blocked", reason="generation_preflight_timeout"), 3
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, (TypeError, ValueError)) else "generation_preflight_invalid"
        return _result(status="blocked", reason=reason, preflight=preflight), 3

    state_dir = preflight_dir or root / ".local" / "gpt-scheduled-import" / "preflight"
    snapshots = package_dir or root / ".local" / "gpt-scheduled-import" / "research-packages"
    try:
        preflight_path = _preflight_path(mode, identity, directory=state_dir)
        package_path = _package_path(mode, identity, automation_id, directory=snapshots)
    except ValueError as exc:
        return _result(status="blocked", reason=str(exc), mode=mode, identity=identity,
                       preflight=preflight), 3

    # A same-run package is immutable and reusable; never invoke ChatGPT twice
    # or replace its evidence under the same occurrence/run identity.
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package_identity = package.get("occurrence_id" if mode == "scheduled" else "manual_run_id")
            if package_identity != identity or not isinstance(package.get("sources"), list):
                raise ValueError("research_package_identity_mismatch")
            if mode == "scheduled" and (
                package.get("category") != category or package.get("topic") != topic
            ):
                raise ValueError("existing_research_package_request_mismatch")
            if package.get("status") != "evidence_available":
                raise ValueError("existing_research_package_has_no_evidence")
            if not preflight_path.exists():
                return _result(status="blocked", reason="existing_package_preflight_missing",
                               mode=mode, identity=identity, preflight=preflight), 3
            saved_preflight = _json_object(
                preflight_path.read_text(encoding="utf-8"), limit=MAX_PREFLIGHT_BYTES,
                failure="saved_preflight_invalid",
            )
            saved_mode, saved_identity, _ = _identity(saved_preflight, automation_id)
            if (saved_mode, saved_identity) != (mode, identity):
                raise ValueError("saved_preflight_identity_mismatch")
            if mode == "scheduled" and saved_preflight.get("scheduled_request") != preflight.get("scheduled_request"):
                raise ValueError("saved_preflight_request_mismatch")
            return _result(status="evidence_available", mode=mode, identity=identity,
                           preflight=saved_preflight, preflight_path=preflight_path,
                           research_path=package_path, source_count=len(package["sources"])), 0
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "existing_research_package_invalid"
            return _result(status="blocked", reason=reason, mode=mode, identity=identity,
                           preflight=preflight), 3

    try:
        _write_immutable(preflight_path, preflight_text.encode("utf-8"))
    except FileExistsError:
        return _result(status="blocked", reason="preflight_artifact_already_exists",
                       mode=mode, identity=identity, preflight=preflight,
                       preflight_path=preflight_path), 3
    except OSError:
        return _result(status="blocked", reason="preflight_artifact_save_failed",
                       mode=mode, identity=identity, preflight=preflight), 3

    broker_name = "scheduled-research-broker.py" if mode == "scheduled" else "manual-research-broker.py"
    broker_command = [
        python, str(root / "scripts" / broker_name),
        "--automation-id", automation_id, "--category", category, "--topic", topic,
    ]
    try:
        researched = command_runner(
            broker_command, cwd=root, input=preflight_text, capture_output=True,
            text=True, encoding="utf-8", timeout=620, check=False,
        )
        broker_result = _json_object(
            researched.stdout, limit=MAX_BROKER_BYTES,
            failure="research_broker_invalid_response",
        )
    except subprocess.TimeoutExpired:
        return _result(status="blocked", reason="research_broker_timeout", mode=mode,
                       identity=identity, preflight=preflight, preflight_path=preflight_path), 4
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return _result(status="blocked", reason="research_broker_unavailable", mode=mode,
                       identity=identity, preflight=preflight, preflight_path=preflight_path), 4

    if researched.returncode != 0 or broker_result.get("status") != "evidence_available":
        reason = broker_result.get("reason")
        safe_reason = reason if isinstance(reason, str) else "research_evidence_unavailable"
        return _result(status="blocked", reason=safe_reason, mode=mode, identity=identity,
                       preflight=preflight, preflight_path=preflight_path), 4

    reported_path = broker_result.get("path")
    if not isinstance(reported_path, str):
        return _result(status="blocked", reason="research_package_path_missing", mode=mode,
                       identity=identity, preflight=preflight, preflight_path=preflight_path), 4
    actual_path = Path(reported_path).resolve(strict=False)
    try:
        actual_path.relative_to(snapshots.resolve(strict=False))
        package = json.loads(actual_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return _result(status="blocked", reason="research_package_not_verified", mode=mode,
                       identity=identity, preflight=preflight, preflight_path=preflight_path), 4
    expected_identity_key = "occurrence_id" if mode == "scheduled" else "manual_run_id"
    if package.get(expected_identity_key) != identity or package.get("status") != "evidence_available":
        return _result(status="blocked", reason="research_package_identity_mismatch", mode=mode,
                       identity=identity, preflight=preflight, preflight_path=preflight_path), 4
    return _result(status="evidence_available", mode=mode, identity=identity,
                   preflight=preflight, preflight_path=preflight_path,
                   research_path=actual_path, source_count=len(package.get("sources", []))), 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the actual Desktop invocation, run local duplicate preflight, then invoke its fixed research broker"
    )
    parser.add_argument("--automation-id", required=True)
    parser.add_argument("--category", required=True, choices=("politics", "economy", "technology", "general"))
    parser.add_argument("--language-code", required=True)
    parser.add_argument("--target-country", required=True)
    parser.add_argument("--target-blog-id", required=True)
    parser.add_argument("--event-group-id", required=True)
    parser.add_argument("--topic", required=True)
    args = parser.parse_args(argv)
    result, code = run_stage(
        automation_id=args.automation_id, category=args.category,
        language_code=args.language_code, target_country=args.target_country,
        target_blog_id=args.target_blog_id, event_group_id=args.event_group_id,
        topic=args.topic,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
