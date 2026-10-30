"""Read-only scheduled-content duplicate preflight through the local Dashboard proxy."""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ORIGIN = "http://127.0.0.1:3100"
ENDPOINT = f"{ORIGIN}/api/research/content-imports/duplicate-check"
KNOWN_STATUSES = {"already_published", "already_imported", "failed_only", "not_found", "unknown"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _open_local_proxy(request: Request, *, timeout: int):
    return build_opener(_NoRedirect).open(request, timeout=timeout)


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


def check_duplicate(payload: dict[str, Any], *, opener=_open_local_proxy) -> dict[str, Any]:
    """Call only the same-origin read-only duplicate preflight; never access secrets."""
    request = Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        response_context = opener(request, timeout=20)
    except HTTPError as exc:
        validation_detail = _safe_http_validation_detail(exc) if exc.code == 422 else []
        return {
            "status": "unknown",
            "reason": "duplicate_preflight_http_error",
            "http_status": exc.code,
            "transport_error_type": "HTTPError",
            **({"validation_detail": validation_detail} if validation_detail else {}),
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "status": "unknown",
            "reason": "duplicate_preflight_transport_error",
            "transport_error_type": type(exc).__name__,
        }
    try:
        with response_context as response:
            http_status = getattr(response, "status", getattr(response, "code", None))
            if isinstance(http_status, int) and not 200 <= http_status < 300:
                return {
                    "status": "unknown",
                    "reason": "duplicate_preflight_http_error",
                    "http_status": http_status,
                    "transport_error_type": "HTTPResponse",
                }
            raw = response.read(128_001)
    except (TimeoutError, OSError) as exc:
        return {
            "status": "unknown",
            "reason": "duplicate_preflight_response_read_error",
            "transport_error_type": type(exc).__name__,
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
    parser.add_argument("--language-code", required=True, choices=("ko", "en", "ja", "zh-CN"))
    parser.add_argument("--target-country", required=True, help="Uppercase ISO country code")
    parser.add_argument("--target-blog-id", required=True)
    parser.add_argument("--trade-date", help="ISO date; omit for non-market-close work")
    parser.add_argument("--event-group-id", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--content-id", help="Optional existing content UUID to check")
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
    result = check_duplicate(payload)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.stage == "generation" and result.get("draft_import_allowed") is True:
        return 0
    return 3 if result["status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
