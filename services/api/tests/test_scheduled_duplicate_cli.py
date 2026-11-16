from __future__ import annotations

import json
from io import BytesIO
from typing import Self
from urllib.error import HTTPError, URLError

import pytest

from scripts.scheduled_duplicate_check import ENDPOINT, ORIGIN, check_duplicate, main


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


@pytest.mark.parametrize("language", ["ko", "en", "ja", "zh-CN", "de", "pt-BR", "vi"])
def test_duplicate_preflight_cli_accepts_registered_language_tags(
    language: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    def fake_check(payload: dict[str, object]) -> dict[str, object]:
        seen.update(payload)
        return {"status": "not_found", "local_status": "not_found",
                "draft_import_allowed": False, "remote_status": "not_checked"}

    monkeypatch.setattr("scripts.scheduled_duplicate_check.check_duplicate", fake_check)
    result = main([
        "--language-code", language, "--target-country", "DE", "--target-blog-id", "5857406989226346280",
        "--event-group-id", "event-de-20261103", "--topic", "A verified current policy issue",
    ])

    assert result == 0
    assert seen["language_code"] == language
    assert json.loads(capsys.readouterr().out)["status"] == "not_found"


def test_duplicate_preflight_cli_normalizes_bcp47_tag_and_rejects_invalid_tag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "scripts.scheduled_duplicate_check.check_duplicate",
        lambda payload: (seen.update(payload) or {"status": "not_found"}),
    )
    assert main([
        "--language-code", "pt-br", "--target-country", "BR", "--target-blog-id", "2780805325207451782",
        "--event-group-id", "event-br-20261103", "--topic", "A verified current policy issue",
    ]) == 0
    assert seen["language_code"] == "pt-BR"
    capsys.readouterr()

    with pytest.raises(SystemExit) as error:
        main([
            "--language-code", "bad_tag", "--target-country", "BR", "--target-blog-id", "2780805325207451782",
            "--event-group-id", "event-br-20261103", "--topic", "A verified current policy issue",
        ])
    assert error.value.code == 2


def test_duplicate_preflight_rejects_non_numeric_blog_id_before_http(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.scheduled_duplicate_check.check_duplicate",
        lambda _payload: pytest.fail("invalid Blogger ID must not reach HTTP"),
    )
    with pytest.raises(SystemExit) as error:
        main([
            "--language-code", "ja", "--target-country", "JP",
            "--target-blog-id", "<registered Blogger ID>",
            "--event-group-id", "market-close-jp-20261105",
            "--topic", "Japan market close",
        ])
    assert error.value.code == 2
    assert "registered numeric Blogger ID" in capsys.readouterr().err


def test_duplicate_preflight_reports_exact_safe_invocation_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("current_codex_session_record_missing_or_ambiguous")

    monkeypatch.setattr("woori.automation_invocation.resolve_current_invocation", unavailable)
    result = main([
        "--language-code", "de", "--target-country", "DE", "--target-blog-id", "5857406989226346280",
        "--event-group-id", "event-de-20261103", "--topic", "A verified current policy issue",
        "--automation-id", "automation-13", "--stage", "generation",
    ])

    assert result == 3
    response = json.loads(capsys.readouterr().out)
    assert response["reason"] == "current_codex_session_record_missing_or_ambiguous"
    assert response["draft_import_allowed"] is False
