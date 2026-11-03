"""Read-only scheduled-content duplicate preflight through the local Dashboard proxy."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "api"))
from woori.language_codes import normalize_language_tag

ORIGIN = "http://127.0.0.1:3100"
ENDPOINT = f"{ORIGIN}/api/research/content-imports/duplicate-check"
KNOWN_STATUSES = {"already_published", "already_imported", "failed_only", "not_found", "unknown"}
REQUEST_TIMEOUT_SECONDS = 4
MAX_ATTEMPTS = 3


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _language_code(value: str) -> str:
    """Canonicalize valid BCP 47 tags; registered blog policy is checked downstream."""
    try:
        return normalize_language_tag(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a valid BCP 47 language tag") from exc


def _open_local_proxy(request: Request, *, timeout: int):
    # This fixed loopback-only endpoint must never be routed through a machine proxy.
    return build_opener(ProxyHandler({}), _NoRedirect).open(request, timeout=timeout)


def _transport_reason(exc: BaseException) -> str:
    """Classify transport failures without persisting hostnames or raw exception text."""
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, (TimeoutError,)):
        return "timeout"
    if isinstance(reason, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(reason, ConnectionResetError):
        return "connection_reset"
    if isinstance(reason, OSError):
        if getattr(reason, "winerror", None) == 11001:
            return "name_resolution"
        if getattr(reason, "winerror", None) in {10061} or getattr(reason, "errno", None) in {111, 61}:
            return "connection_refused"
        if getattr(reason, "winerror", None) in {10060} or getattr(reason, "errno", None) in {110, 60}:
            return "timeout"
        if getattr(reason, "winerror", None) in {10051, 10065} or getattr(reason, "errno", None) in {101, 113}:
            return "network_unreachable"
        return "socket_error"
    if isinstance(reason, str) and "name or service not known" in reason.casefold():
        return "name_resolution"
    return "other_transport"


def _safe_http_validation_detail(error: HTTPError) -> list[dict[str, str]]:
    """Return only Pydantic locations/messages, never echoed request values."""
    try:
        payload = json.loads(error.read(32_001).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, list):
        return []
    return [
        {
            "location": ".".join(str(part) for part in issue.get("loc", ()))[:120],
            "message": " ".join(str(issue.get("msg", "Invalid request")).split())[:200],
        }
        for issue in detail[:5]
        if isinstance(issue, dict)
    ]


def _broker(payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    try:
        run = subprocess.run(
            [sys.executable, str(root / "scripts" / "scheduled-preflight-broker.py")],
            input=json.dumps(payload), text=True, capture_output=True, cwd=root,
            timeout=25, check=False,
        )
        result = json.loads(run.stdout)
        if run.returncode == 0 and isinstance(result, dict) and result.get("status") in KNOWN_STATUSES:
            return result
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {"status": "unknown", "local_status": "unknown", "draft_import_allowed": False,
            "research_allowed": True, "local_save_allowed": True, "import_status": "pending",
            "hold_reason": "duplicate_check_unavailable", "reason": "local_broker_unavailable"}


def check_duplicate(payload: dict[str, Any], *, opener=_open_local_proxy, fallback=_broker) -> dict[str, Any]:
    result = _check_proxy(payload, opener=opener)
    outage = result.get("reason") == "duplicate_preflight_transport_error" or (
        result.get("reason") == "duplicate_preflight_http_error" and result.get("http_status", 0) >= 500
    )
    if payload.get("stage") == "generation" and outage:
        return {**fallback(payload), "dashboard_failure": result}
    return result


def _check_proxy(payload: dict[str, Any], *, opener=_open_local_proxy) -> dict[str, Any]:
    """Call only the same-origin read-only duplicate preflight; never access secrets."""
    request = Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        method="POST",
    )
    last_transport: BaseException | None = None
    raw: bytes | None = None
    http_status: int | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response_context = opener(request, timeout=REQUEST_TIMEOUT_SECONDS)
            with response_context as response:
                http_status = getattr(response, "status", getattr(response, "code", None))
                if isinstance(http_status, int) and not 200 <= http_status < 300:
                    return {
                        "status": "unknown", "reason": "duplicate_preflight_http_error",
                        "http_status": http_status, "transport_error_type": "HTTPResponse",
                        "attempts": attempt,
                    }
                raw = response.read(128_001)
            break
        except HTTPError as exc:
            validation_detail = _safe_http_validation_detail(exc) if exc.code == 422 else []
            return {
                "status": "unknown", "reason": "duplicate_preflight_http_error",
                "http_status": exc.code, "transport_error_type": "HTTPError",
                "attempts": attempt,
                **({"validation_detail": validation_detail} if validation_detail else {}),
            }
        except (URLError, TimeoutError, OSError) as exc:
            last_transport = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(0.15 * attempt)
    if raw is None:
        failure = last_transport or OSError("no_response")
        return {
            "status": "unknown", "reason": "duplicate_preflight_transport_error",
            "transport_error_type": type(failure).__name__,
            "transport_reason": _transport_reason(failure), "attempts": MAX_ATTEMPTS,
        }
    if len(raw) > 128_000:
        return {"status": "unknown", "reason": "duplicate_preflight_response_too_large"}
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {
            "status": "unknown",
            "reason": "duplicate_preflight_invalid_json",
            "http_status": http_status if isinstance(http_status, int) else None,
        }
    if not isinstance(result, dict) or result.get("status") not in KNOWN_STATUSES:
        return {
            "status": "unknown",
            "reason": "duplicate_preflight_invalid_response",
            **({"http_status": http_status} if isinstance(http_status, int) else {}),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only duplicate check for one Codex Scheduled occurrence"
    )
    parser.add_argument("--language-code", required=True, type=_language_code)
    parser.add_argument("--target-country", required=True, help="Uppercase ISO country code")
    parser.add_argument("--target-blog-id", required=True)
    parser.add_argument("--trade-date", help="ISO date; omit for non-market-close work")
    parser.add_argument("--event-group-id", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--content-id", help="Optional existing content UUID to check")
    parser.add_argument(
        "--automation-id",
        help="Exact ID from the current verified Codex Desktop Automation session",
    )
    parser.add_argument(
        "--stage",
        choices=("generation", "publication"),
        help="generation checks local history only; publication includes the complete Blogger read",
    )
    args = parser.parse_args(argv)
    if args.trade_date:
        try:
            args.trade_date = date.fromisoformat(args.trade_date).isoformat()
        except ValueError:
            parser.error("--trade-date must be YYYY-MM-DD")
    if (
        not args.target_country.isascii()
        or not args.target_country.isupper()
        or not (2 <= len(args.target_country) <= 3)
    ):
        parser.error("--target-country must be an uppercase 2-3 character code")
    if not 3 <= len(args.event_group_id.strip()) <= 128:
        parser.error("--event-group-id must contain 3 to 128 characters; use a concise stable event key")
    if not 3 <= len(args.topic.strip()) <= 300:
        parser.error("--topic must contain 3 to 300 characters")
    payload = {
        "language_code": args.language_code,
        "target_country": args.target_country,
        "target_blog_id": args.target_blog_id,
        "trade_date": args.trade_date,
        "event_group_id": args.event_group_id,
        "topic": args.topic,
        "content_id": args.content_id,
    }
    if args.stage:
        payload["stage"] = args.stage
    invocation = None
    if args.stage == "generation":
        try:
            from woori.automation_invocation import (
                current_automation_id,
                resolve_current_invocation,
            )
            from woori.scheduled_pending import record_progress
            from woori.scheduled_slot_gate import wait_for_scheduled_slot

            project_root = Path(__file__).resolve().parents[1]
            automation_id = args.automation_id or current_automation_id(
                project_root=project_root
            )
            invocation = resolve_current_invocation(
                automation_id,
                project_root=project_root,
            )
        except (OSError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                # Resolver ValueErrors are bounded internal reason codes; retain
                # them so operators can distinguish a missing session from an
                # inactive schedule without treating self-report as authority.
                failure_reason = str(exc)[:120]
            elif isinstance(exc, TypeError):
                failure_reason = "scheduled_invocation_metadata_invalid"
            else:
                # OS errors may contain user-specific filesystem paths.
                failure_reason = "scheduled_invocation_storage_unavailable"
            result = {
                "status": "unknown",
                "local_status": "unknown",
                "draft_import_allowed": False,
                "reason": failure_reason,
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 3
        if invocation and invocation.get("execution_mode") == "scheduled":
            slot_gate = wait_for_scheduled_slot(
                invocation,
                project_root / ".local/gpt-scheduled-import",
            )
            if slot_gate["state"] != "ready":
                result = {"status": "unknown", "local_status": "unknown",
                          "draft_import_allowed": False, "reason": slot_gate["reason"]}
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 3
        if invocation:
            try:
                record_progress(
                    project_root / ".local/gpt-scheduled-import",
                    invocation,
                    "duplicate_check_running",
                )
            except (OSError, TypeError, ValueError):
                result = {"status": "unknown", "local_status": "unknown",
                          "draft_import_allowed": False,
                          "reason": "duplicate_check_progress_unavailable"}
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 3
    try:
        result = check_duplicate(payload)
    except Exception:  # noqa: BLE001 - preflight failures must remain fail-closed and sanitized
        result = {"status": "unknown", "local_status": "unknown",
                  "draft_import_allowed": False,
                  "reason": "duplicate_preflight_internal_error"}
    if invocation:
        local_status = str(result.get("local_status", result.get("status", "unknown")))[:40]
        remote_status = str(result.get("remote_status", "not_checked"))[:40]
        draft_allowed = result.get("draft_import_allowed") is True
        progress_reason = (
            f"local={local_status};remote={remote_status};"
            f"draft_import_allowed={str(draft_allowed).lower()}"
        )
        try:
            from woori.scheduled_pending import record_progress

            record_progress(
                project_root / ".local/gpt-scheduled-import",
                invocation,
                "duplicate_check_completed",
                progress_reason,
            )
        except (OSError, TypeError, ValueError):
            result = {**result, "status": "unknown", "draft_import_allowed": False,
                      "reason": "duplicate_check_completion_not_recorded"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.stage == "generation" and result.get("draft_import_allowed") is True:
        return 0
    return 3 if result["status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
