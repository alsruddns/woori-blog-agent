from __future__ import annotations

import json
from typing import Self
from urllib.error import URLError

from scripts.scheduled_duplicate_check import ENDPOINT, ORIGIN, check_duplicate


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_duplicate_cli_calls_only_fixed_local_dashboard_preflight() -> None:
    payload = {
        "language_code": "ko", "target_country": "KR", "target_blog_id": "3321654108096579717",
        "trade_date": "2026-10-29", "event_group_id": "kr-close-20261029",
        "topic": "Korean market close", "content_id": None,
    }
    seen: dict[str, object] = {}

    def opener(request, *, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.method
        seen["origin"] = request.get_header("Origin")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return FakeResponse({"status": "not_found", "blogger_read_complete": True})

    result = check_duplicate(payload, opener=opener)

    assert result["status"] == "not_found"
    assert seen == {
        "url": ENDPOINT,
        "method": "POST",
        "origin": ORIGIN,
        "body": payload,
        "timeout": 20,
    }


def test_duplicate_cli_converts_transport_error_to_unknown() -> None:
    def opener(_request, *, timeout):
        raise URLError("offline")

    assert check_duplicate({}, opener=opener) == {
        "status": "unknown", "reason": "duplicate_preflight_unavailable"
    }


def test_duplicate_cli_does_not_treat_invalid_response_as_absence() -> None:
    result = check_duplicate({}, opener=lambda *_args, **_kwargs: FakeResponse({"status": "clear"}))
    assert result == {"status": "unknown", "reason": "duplicate_preflight_invalid_response"}
