from __future__ import annotations

import json
from io import BytesIO
from typing import Self
from urllib.error import HTTPError, URLError

from scripts.scheduled_duplicate_check import ENDPOINT, ORIGIN, check_duplicate


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_duplicate_cli_calls_only_fixed_local_dashboard_preflight() -> None:
    payload = {
        "language_code": "ko", "target_country": "KR", "target_blog_id": "3321654108096579717",
        "trade_date": "2026-10-29", "event_group_id": "kr-close-20261029",
        "topic": "Korean market close", "content_id": None, "stage": "publication",
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
        "timeout": 4,
    }


def test_duplicate_cli_converts_transport_error_to_unknown() -> None:
    calls = 0

    def opener(_request, *, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 4
        raise URLError(ConnectionRefusedError(10061, "connection refused"))

    assert check_duplicate({}, opener=opener) == {
        "status": "unknown", "reason": "duplicate_preflight_transport_error",
        "transport_error_type": "URLError", "transport_reason": "connection_refused",
        "attempts": 3,
    }
    assert calls == 3


def test_duplicate_cli_recovers_after_transient_loopback_failure() -> None:
    calls = 0

    def opener(request, *, timeout):
        nonlocal calls
        calls += 1
        assert request.full_url == ENDPOINT and request.method == "POST"
        assert timeout == 4
        if calls == 1:
            raise URLError(ConnectionResetError(10054, "connection reset"))
        return FakeResponse({"status": "unknown", "draft_import_allowed": True,
                             "local_status": "failed_only", "remote_status": "not_checked"})

    result = check_duplicate({"stage": "generation"}, opener=opener)
    assert calls == 2
    assert result["draft_import_allowed"] is True
    assert result["local_status"] == "failed_only"


def test_duplicate_cli_reports_http_status_without_error_body() -> None:
    def opener(_request, *, timeout):
        raise HTTPError(ENDPOINT, 503, "upstream unavailable", {}, None)

    assert check_duplicate({}, opener=opener) == {
        "status": "unknown", "reason": "duplicate_preflight_http_error",
        "http_status": 503, "transport_error_type": "HTTPError",
        "attempts": 1,
    }


def test_duplicate_cli_preserves_sanitized_validation_location_for_422() -> None:
    body = json.dumps({"detail": [{"loc": ["body", "event_group_id"],
                                   "msg": "String should have at most 128 characters",
                                   "input": "must-not-be-returned"}]}).encode()

    def opener(_request, *, timeout):
        raise HTTPError(ENDPOINT, 422, "invalid input", {}, BytesIO(body))

    result = check_duplicate({}, opener=opener)
    assert result == {
        "status": "unknown", "reason": "duplicate_preflight_http_error",
        "http_status": 422, "transport_error_type": "HTTPError",
        "attempts": 1,
        "validation_detail": [{
            "location": "body.event_group_id",
            "message": "String should have at most 128 characters",
        }],
    }


def test_duplicate_cli_does_not_treat_invalid_response_as_absence() -> None:
    result = check_duplicate({}, opener=lambda *_args, **_kwargs: FakeResponse({"status": "clear"}))
    assert result == {"status": "unknown", "reason": "duplicate_preflight_invalid_response"}
