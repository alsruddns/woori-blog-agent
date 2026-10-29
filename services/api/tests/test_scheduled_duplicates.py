from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from woori import blogger_service, content_imports, scheduled_duplicates
from woori.google_http import GoogleFailure


def test_remote_duplicate_scan_reports_clear_only_after_last_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = iter([
        {"items": [{"id": "1", "title": "An unrelated post"}], "nextPageToken": "next"},
        {"items": [{"id": "2", "title": "Target title"}]},
    ])
    monkeypatch.setattr(blogger_service, "posts", lambda *_args: next(pages))

    result = scheduled_duplicates.find_remote_duplicate(UUID(int=1), "Target title")

    assert result["status"] == "found"
    assert result["post_id"] == "2"


def test_remote_duplicate_scan_never_treats_partial_listing_as_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        blogger_service, "posts",
        lambda *_args: {"items": [], "nextPageToken": "more"},
    )

    result = scheduled_duplicates.find_remote_duplicate(UUID(int=1), "Target title", page_limit=1)

    assert result["status"] == "unknown"
    assert result["reason"] == "blogger_read_scan_limit_reached"


def test_remote_duplicate_scan_keeps_google_read_failures_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: Any) -> dict[str, Any]:
        raise GoogleFailure("unauthorized", status=401)

    monkeypatch.setattr(blogger_service, "posts", fail)

    result = scheduled_duplicates.find_remote_duplicate(UUID(int=1), "Target title")

    assert result["status"] == "unknown"
    assert result["reason"] == "unauthorized"


class _Result:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> Any:
        return self.row

    def fetchall(self) -> list[Any]:
        return self.rows


class _Connection:
    def __init__(self, blog_id: UUID) -> None:
        self.blog_id = blog_id

    def execute(self, query: str, _params: Any = None) -> _Result:
        if "INSERT INTO audit_events" in query:
            return _Result()
        if "FROM blogger_blogs WHERE blog_id=" in query:
            return _Result({"id": self.blog_id, "blog_id": "3321654108096579717",
                            "language_code": "ko", "url": "https://trend-ko.blogspot.com",
                            "active": True, "connection_verified_at": datetime.now(UTC),
                            "oauth_connection_id": uuid4()})
        if "FROM external_content_imports i" in query:
            return _Result(rows=[])
        raise AssertionError("Unexpected database query in duplicate-check test")


def _request() -> content_imports.DuplicateCheckRequest:
    return content_imports.DuplicateCheckRequest(
        language_code="ko", target_country="KR", target_blog_id="3321654108096579717",
        trade_date=date(2026, 10, 29), event_group_id="kr-market-close-2026-10-29",
        topic="Korean market close analysis", content_id="scheduled-content-2026-10-29",
    )


def _prepare_duplicate_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, folders: tuple[str, ...],
) -> None:
    blog_id = uuid4()

    @contextmanager
    def fake_connection():
        yield _Connection(blog_id)

    monkeypatch.setattr(content_imports, "connection", fake_connection)
    fake_file = tmp_path / "services" / "api" / "woori" / "content_imports.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()
    monkeypatch.setattr(content_imports, "__file__", str(fake_file))
    inbox = tmp_path / ".local" / "gpt-scheduled-import"
    for folder in folders:
        directory = inbox / folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "task.ready.json").write_text(json.dumps({"item": {
            "content_id": "scheduled-content-2026-10-29",
            "event_group_id": "kr-market-close-2026-10-29",
        }}), encoding="utf-8")
    monkeypatch.setattr(scheduled_duplicates, "find_remote_duplicate",
                        lambda *_args: {"status": "clear", "reason": "complete_scan"})


def test_duplicate_check_allows_new_original_after_failure_files_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _prepare_duplicate_check(monkeypatch, tmp_path, ("quarantine", "rejected"))

    result = content_imports.scheduled_duplicate_check(_request())

    assert result["status"] == "failed_only"
    assert result["safe_to_create_new_original_id"] is True
    assert result["preserve_failed_files"] is True


@pytest.mark.parametrize("folder", ["incoming", "ready", "processing", "completed"])
def test_duplicate_check_blocks_when_matching_file_is_not_a_failed_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, folder: str,
) -> None:
    _prepare_duplicate_check(monkeypatch, tmp_path, (folder,))

    result = content_imports.scheduled_duplicate_check(_request())

    assert result["status"] == "unknown"
    assert result["reason"] == "matching_file_pending_or_completed_without_database_import"


def test_duplicate_check_never_treats_remote_read_failure_as_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _prepare_duplicate_check(monkeypatch, tmp_path, ())
    monkeypatch.setattr(scheduled_duplicates, "find_remote_duplicate",
                        lambda *_args: {"status": "unknown", "reason": "unauthorized"})

    result = content_imports.scheduled_duplicate_check(_request())

    assert result["status"] == "unknown"
    assert result["reason"] == "unauthorized"
