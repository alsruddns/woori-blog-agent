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


def check_duplicate(payload: dict[str, Any], *, opener=_open_local_proxy) -> dict[str, Any]:
    """Call only the same-origin read-only duplicate preflight; never access secrets."""
    request = Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "unknown", "reason": "duplicate_preflight_unavailable"}
    if not isinstance(result, dict) or result.get("status") not in KNOWN_STATUSES:
        return {"status": "unknown", "reason": "duplicate_preflight_invalid_response"}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only duplicate check for one Codex Scheduled occurrence")
    parser.add_argument("--language-code", required=True, choices=("ko", "en", "ja", "zh-CN"))
    parser.add_argument("--target-country", required=True, help="Uppercase ISO country code")
    parser.add_argument("--target-blog-id", required=True)
    parser.add_argument("--trade-date", help="ISO date; omit for non-market-close work")
    parser.add_argument("--event-group-id", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--content-id", help="Optional existing content UUID to check")
    args = parser.parse_args(argv)
    if args.trade_date:
        try:
            args.trade_date = date.fromisoformat(args.trade_date).isoformat()
        except ValueError:
            parser.error("--trade-date must be YYYY-MM-DD")
    if not args.target_country.isascii() or not args.target_country.isupper() or not (2 <= len(args.target_country) <= 3):
        parser.error("--target-country must be an uppercase 2-3 character code")
    payload = {
        "language_code": args.language_code,
        "target_country": args.target_country,
        "target_blog_id": args.target_blog_id,
        "trade_date": args.trade_date,
        "event_group_id": args.event_group_id,
        "topic": args.topic,
        "content_id": args.content_id,
    }
    result = check_duplicate(payload)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 3 if result["status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
