from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from woori import automation_controls, automation_invocation, scheduled_research


def _occurrence() -> str:
    return "codex-slot:automation-7:20261105T0900KST"


def test_feed_parser_keeps_only_recent_dated_source_metadata():
    now = datetime(2026, 11, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=15)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    fresh = (now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = f"""<?xml version="1.0"?><rss><channel>
      <item><title>Fresh update</title><link>https://www.whitehouse.gov/releases/2026/11/fresh-policy/</link><pubDate>{fresh}</pubDate><description>Summary</description></item>
      <item><title>Old update</title><link>https://www.whitehouse.gov/releases/2026/10/old-policy/</link><pubDate>{old}</pubDate></item>
      <item><title>No date</title><link>https://www.whitehouse.gov/releases/2026/11/no-date/</link></item>
    </channel></rss>""".encode()
    rows = scheduled_research._parse_feed(feed, now=now)
    assert [row["title"] for row in rows] == ["Fresh update"]
    assert rows[0]["feed_excerpt"] == "Summary"


def test_gather_uses_fixed_feed_and_page_urls_and_captures_source_hash(monkeypatch):
    now = datetime(2026, 11, 5, 1, tzinfo=UTC)
    published = (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = f"<rss><channel><item><title>Congressional policy update</title><link>https://www.whitehouse.gov/releases/2026/11/congressional-policy-update/</link><pubDate>{published}</pubDate><description>Release summary</description></item></channel></rss>".encode()
    body = b"<html><main><h1>Congressional policy update</h1><p>" + (b"Evidence sentence about the announced measure. " * 8) + b"</p></main></html>"
    calls = []

    def fake_fetch(provider, url, *, run_id):
        calls.append((provider, url, run_id))
        return feed if url.endswith("/news/feed/") else body

    monkeypatch.setattr(scheduled_research, "_fetch", fake_fetch)
    package = scheduled_research.gather("politics", "Federal policy developments", occurrence_id=_occurrence(), audit_run_id=_occurrence(), now=now)
    assert package["status"] == "evidence_available"
    assert package["sources"][0]["publisher"] == "The White House"
    assert package["sources"][0]["published_at"] == (now - timedelta(hours=1)).isoformat()
    assert package["sources"][0]["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert package["sources"][0]["rights_url"] == "https://www.whitehouse.gov/copyright/"
    assert package["sources"][0]["semantic_review"] == "required"
    assert calls == [
        ("whitehouse_public_news", "https://www.whitehouse.gov/news/feed/", _occurrence()),
        ("whitehouse_public_news", "https://www.whitehouse.gov/releases/2026/11/congressional-policy-update/", _occurrence()),
    ]


def test_gather_distinguishes_fetch_failure_from_no_fresh_items(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(scheduled_research, "_fetch", fail)
    failed = scheduled_research.gather("technology", "cybersecurity policy", occurrence_id=_occurrence())
    assert failed["failure_class"] == "collection_failed"
    assert failed["sources"] == []

    monkeypatch.setattr(scheduled_research, "_fetch", lambda *_args, **_kwargs: b"<rss><channel></channel></rss>")
    empty = scheduled_research.gather("technology", "cybersecurity policy", occurrence_id=_occurrence())
    assert empty["failure_class"] == "no_fresh_source_items"


def test_research_requires_same_live_scheduled_invocation_and_clear_local_preflight(monkeypatch):
    invocation = {
        "automation_id": "automation-7",
        "execution_mode": "scheduled",
        "occurrence_id": _occurrence(),
        "scheduled_slot": "2026-11-05T09:00:00+09:00",
    }
    monkeypatch.setattr(automation_invocation, "resolve_current_invocation", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(automation_controls, "authoring_permission", lambda: {"allowed": True})
    monkeypatch.setattr(scheduled_research, "gather_with_codex_search", lambda *_args, **kwargs: {
        "status": "evidence_available", "occurrence_id": kwargs["occurrence_id"], "sources": [{"url": "fixed"}],
    })
    monkeypatch.setattr(scheduled_research, "write_package", lambda package, *, automation_id: {
        "status": package["status"], "path": "fixture", "source_count": 1,
    })
    preflight = {
        "status": "unknown", "overall_status": "unknown", "remote_status": "not_checked",
        "local_status": "not_found", "draft_import_allowed": True,
        "automation_execution": {"invocation": invocation},
    }
    result = scheduled_research.run_authorized_research(
        automation_id="automation-7", category="politics", topic="US policy", preflight=preflight
    )
    assert result["remote_status"] == "not_checked"
    assert result["overall_status"] == "unknown"
    with pytest.raises(ValueError, match="local_duplicate_preflight_not_clear"):
        scheduled_research.run_authorized_research(
            automation_id="automation-7", category="politics", topic="US policy",
            preflight={**preflight, "local_status": "unknown", "draft_import_allowed": False},
        )


def test_package_is_immutable_and_audited(monkeypatch, tmp_path):
    events = []

    class FakeConnection:
        def execute(self, query, params):
            events.append((query, params))

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(scheduled_research, "connection", fake_connection)
    monkeypatch.setattr(scheduled_research, "PACKAGE_DIR", tmp_path)
    package = {"schema_version": "scheduled-research-package/1.0", "occurrence_id": _occurrence(),
               "category": "politics", "status": "evidence_available", "sources": [{"title": "A"}]}
    result = scheduled_research.write_package(package, automation_id="automation-7")
    path = tmp_path / "automation-7-20261105T0900KST.research.json"
    original = path.read_bytes()
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert json.loads(original)["sources"][0]["title"] == "A"
    assert events[0][1][0] == "research.scheduled_package.saved"
    assert scheduled_research.write_package(package, automation_id="automation-7")["sha256"] == result["sha256"]
    with pytest.raises(ValueError, match="package_conflict"):
        scheduled_research.write_package({**package, "topic": "different"}, automation_id="automation-7")
    assert path.read_bytes() == original


def test_codex_search_package_requires_real_search_url_exact_excerpt_and_fresh_date(monkeypatch):
    from woori import codex_runner

    now = datetime(2026, 11, 5, 1, tzinfo=UTC)
    excerpt = "The committee issued its final decision after reviewing the November filing."
    search_result = {
        "url": "https://example.gov/news/decision",
        "title": "Agency decision on the November filing",
        "domain": "example.gov",
        "snippet": f"Published November 4, 2026. {excerpt}",
    }

    def fake_execute(*_args, **kwargs):
        assert kwargs["require_web_research"] is True
        assert kwargs["require_opened_sources"] is False
        return {
            "sources": [{
                "title": search_result["title"], "publisher": "Example Agency",
                "url": search_result["url"], "published_at": "2026-11-04",
                "event_date": "2026-11-04", "evidence_excerpt": excerpt,
            }]
        }, {"model": "gpt-6-luna", "web_search_count": 1, "execution_id": "cli-run-1", "searched_sources": [search_result]}

    monkeypatch.setattr(codex_runner, "execute", fake_execute)
    package = scheduled_research.gather_with_codex_search(
        "politics", "agency filing", occurrence_id=_occurrence(), now=now
    )
    assert package["status"] == "evidence_available"
    assert package["research_engine"] == "codex_cli_chatgpt_search"
    assert package["sources"][0]["url"] == search_result["url"]
    assert package["sources"][0]["published_at"] == "2026-11-04"
    assert package["sources"][0]["evidence_excerpt"] == search_result["snippet"]
    assert package["sources"][0]["model_excerpt_matches_search_snippet"] is True


def test_codex_search_package_rejects_unobserved_urls_and_nonmatching_excerpt(monkeypatch):
    from woori import codex_runner

    monkeypatch.setattr(codex_runner, "execute", lambda *_args, **_kwargs: (
        {"sources": [{"title": "Agency report", "publisher": "Agency", "url": "https://fake.gov/x",
                      "published_at": "2026-11-04", "evidence_excerpt": "A fabricated evidence excerpt with enough characters."}]},
        {"model": "gpt-6-luna", "web_search_count": 1, "execution_id": "cli-run-2", "searched_sources": [
            {"url": "https://example.gov/report", "title": "Real", "domain": "example.gov", "snippet": "A real search snippet."}
        ]},
    ))
    package = scheduled_research.gather_with_codex_search(
        "general", "topic", occurrence_id=_occurrence(), now=datetime(2026, 11, 5, 1, tzinfo=UTC)
    )
    assert package["status"] == "evidence_unavailable"
    assert package["failure_class"] == "source_validation_failed"
    assert {item["reason"] for item in package["collection_failures"]} == {"source_not_in_search_results"}


def test_scheduled_broker_writes_codex_sources_into_snapshot_package(monkeypatch, tmp_path):
    from woori import codex_runner

    invocation = {
        "automation_id": "automation-7", "execution_mode": "scheduled",
        "occurrence_id": _occurrence(), "scheduled_slot": "2026-11-05T09:00:00+09:00",
    }
    result = {
        "title": "Agency announces policy change",
        "publisher": "Example Agency",
        "url": "https://example.gov/news/policy-change",
        "published_at": "2026-11-04",
        "event_date": "2026-11-04",
        "evidence_excerpt": "The agency said the rule takes effect next month.",
    }
    snippet = "Published November 4, 2026. The agency said the rule takes effect next month."
    monkeypatch.setattr(automation_invocation, "resolve_current_invocation", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(automation_controls, "authoring_permission", lambda: {"allowed": True})
    monkeypatch.setattr(codex_runner, "execute", lambda *_args, **_kwargs: (
        {"sources": [result]},
        {"model": "gpt-6-luna", "web_search_count": 1, "execution_id": "scheduled-cli-run",
         "searched_sources": [{"url": result["url"], "title": result["title"], "domain": "example.gov", "snippet": snippet}]},
    ))
    events = []

    class FakeConnection:
        def execute(self, query, params):
            events.append((query, params))

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(scheduled_research, "connection", fake_connection)
    monkeypatch.setattr(scheduled_research, "PACKAGE_DIR", tmp_path)
    preflight = {
        "status": "unknown", "remote_status": "not_checked", "local_status": "not_found",
        "draft_import_allowed": True,
        "automation_execution": {"invocation": invocation},
    }
    outcome = scheduled_research.run_authorized_research(
        automation_id="automation-7", category="politics", topic="agency rule change",
        preflight=preflight,
    )
    snapshot = json.loads(Path(outcome["path"]).read_text(encoding="utf-8"))
    assert outcome["status"] == "evidence_available"
    assert outcome["overall_status"] == "unknown"
    assert outcome["remote_status"] == "not_checked"
    assert snapshot["research_engine"] == "codex_cli_chatgpt_search"
    assert snapshot["sources"][0]["url"] == result["url"]
    assert snapshot["sources"][0]["published_at"] == "2026-11-04"
    assert snapshot["sources"][0]["evidence_excerpt"] == snippet
    assert snapshot["sources"][0]["semantic_review"] == "required"
    assert events[0][1][0] == "research.scheduled_package.saved"
