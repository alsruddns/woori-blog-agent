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
        assert kwargs["require_opened_sources"] is True
        return {
            "sources": [{
                "title": search_result["title"], "publisher": "Example Agency",
                "url": search_result["url"], "published_at": "2026-11-04",
                "event_date": "2026-11-04", "evidence_excerpt": excerpt,
            }]
        }, {"model": "gpt-6-luna", "web_search_count": 1, "execution_id": "cli-run-1",
            "opened_urls": {search_result["url"] + "?trk=article-ssr": "2026-11-05T00:59:00+00:00"},
            "searched_sources": [search_result]}

    monkeypatch.setattr(codex_runner, "execute", fake_execute)
    package = scheduled_research.gather_with_codex_search(
        "politics", "agency filing", occurrence_id=_occurrence(), now=now
    )
    assert package["status"] == "evidence_available"
    assert package["research_engine"] == "codex_cli_chatgpt_search"
    assert package["sources"][0]["url"] == search_result["url"]
    assert package["sources"][0]["published_at"] == "2026-11-04"
    assert package["sources"][0]["evidence_excerpt"] == excerpt
    assert package["sources"][0]["model_excerpt_matches_search_snippet"] is True
    assert package["sources"][0]["source_opened_at"] == "2026-11-05T00:59:00+00:00"
    assert package["sources"][0]["source_evidence_method"] == "codex_cli_chatgpt_opened_page_model_excerpt"


def test_codex_search_package_rejects_unobserved_urls_and_nonmatching_excerpt(monkeypatch):
    from woori import codex_runner

    monkeypatch.setattr(codex_runner, "execute", lambda *_args, **_kwargs: (
        {"sources": [{"title": "Agency report", "publisher": "Agency", "url": "https://fake.gov/x",
                      "published_at": "2026-11-04", "evidence_excerpt": "A fabricated evidence excerpt with enough characters."}]},
        {"model": "gpt-6-luna", "web_search_count": 1, "execution_id": "cli-run-2",
         "opened_urls": {}, "searched_sources": [
            {"url": "https://example.gov/report", "title": "Real", "domain": "example.gov", "snippet": "A real search snippet."}
        ]},
    ))
    package = scheduled_research.gather_with_codex_search(
        "general", "topic", occurrence_id=_occurrence(), now=datetime(2026, 11, 5, 1, tzinfo=UTC)
    )
    assert package["status"] == "evidence_unavailable"
    assert package["failure_class"] == "source_validation_failed"
    assert {item["reason"] for item in package["collection_failures"]} == {"source_not_in_search_results"}


def test_codex_search_package_requires_opened_source_and_marks_unverified_excerpt(monkeypatch):
    from woori import codex_runner

    url = "https://example.gov/report"
    snippet = "The agency published the report on November 4 and described its findings."
    result = {"title": "Agency report", "publisher": "Agency", "url": url,
              "published_at": "2026-11-04", "event_date": None,
              "evidence_excerpt": "The agency published the report on November 4 and described its findings."}
    evidence = {"model": "gpt-6-luna", "web_search_count": 1, "execution_id": "cli-run-3",
                "searched_sources": [{"url": url, "title": "Agency report", "domain": "example.gov",
                                      "snippet": snippet}], "opened_urls": {}}
    monkeypatch.setattr(codex_runner, "execute", lambda *_args, **_kwargs: ({"sources": [result]}, evidence))
    package = scheduled_research.gather_with_codex_search(
        "general", "agency report", occurrence_id=_occurrence(),
        now=datetime(2026, 11, 5, 1, tzinfo=UTC),
    )
    assert package["status"] == "evidence_unavailable"
    assert package["collection_failures"][0]["reason"] == "source_page_not_opened"

    evidence["opened_urls"] = {url: "2026-11-05T00:59:00+00:00"}
    result["evidence_excerpt"] = "The report contains findings about the agency."
    package = scheduled_research.gather_with_codex_search(
        "general", "agency report", occurrence_id=_occurrence(),
        now=datetime(2026, 11, 5, 1, tzinfo=UTC),
    )
    assert package["status"] == "evidence_available"
    assert package["sources"][0]["model_excerpt_matches_search_snippet"] is False
    assert "not independently verified" in " ".join(package["limitations"])


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
         "opened_urls": {result["url"]: "2026-11-05T00:59:00+00:00"},
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
    assert snapshot["sources"][0]["evidence_excerpt"] == result["evidence_excerpt"]
    assert snapshot["sources"][0]["semantic_review"] == "required"
    assert events[0][1][0] == "research.scheduled_package.saved"


@pytest.mark.parametrize("failure_class", ["source_validation_failed", "no_current_sources"])
def test_scheduled_search_failure_does_not_fall_back_to_category_feed(
    monkeypatch, tmp_path, failure_class,
):
    invocation = {
        "automation_id": "automation-8", "execution_mode": "scheduled",
        "occurrence_id": "codex-slot:automation-8:20261105T2000KST",
        "scheduled_slot": "2026-11-05T20:00:00+09:00",
    }
    monkeypatch.setattr(automation_invocation, "resolve_current_invocation", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(automation_controls, "authoring_permission", lambda: {"allowed": True})
    package = {
        "schema_version": "scheduled-research-package/1.0",
        "occurrence_id": invocation["occurrence_id"],
        "category": "economy",
        "topic": "Vietnam's recent economic developments",
        "research_engine": "codex_cli_chatgpt_search",
        "status": "evidence_unavailable",
        "failure_class": failure_class,
        "sources": [],
    }
    monkeypatch.setattr(scheduled_research, "gather_with_codex_search", lambda *_args, **_kwargs: package)

    def forbidden_fallback(*_args, **_kwargs):
        pytest.fail("scheduled research must not replace failed live-search evidence with a category feed")

    monkeypatch.setattr(scheduled_research, "gather", forbidden_fallback)
    saved = {}

    def capture_package(value, *, automation_id):
        saved["package"] = value
        saved["automation_id"] = automation_id
        return {"status": value["status"], "path": str(tmp_path / "snapshot.json"), "source_count": 0}

    monkeypatch.setattr(scheduled_research, "write_package", capture_package)
    preflight = {
        "status": "unknown", "remote_status": "not_checked", "local_status": "not_found",
        "draft_import_allowed": True,
        "automation_execution": {"invocation": invocation},
    }

    result = scheduled_research.run_authorized_research(
        automation_id="automation-8", category="economy",
        topic="Vietnam's recent economic developments", preflight=preflight,
    )

    assert result["status"] == "evidence_unavailable"
    assert result["execution_mode"] == "scheduled"
    assert result["occurrence_id"] == invocation["occurrence_id"]
    assert saved["automation_id"] == "automation-8"
    assert saved["package"]["research_engine"] == "codex_cli_chatgpt_search"
    assert saved["package"]["failure_class"] == failure_class
    assert saved["package"]["sources"] == []


@pytest.mark.parametrize("search_error", [
    "codex_not_installed", "web_research_not_observed", "codex_execution_failed",
])
def test_scheduled_search_infrastructure_errors_do_not_use_category_feed(monkeypatch, search_error):
    invocation = {
        "automation_id": "automation-8", "execution_mode": "scheduled",
        "occurrence_id": "codex-slot:automation-8:20261105T2000KST",
        "scheduled_slot": "2026-11-05T20:00:00+09:00",
    }
    monkeypatch.setattr(automation_invocation, "resolve_current_invocation", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(automation_controls, "authoring_permission", lambda: {"allowed": True})
    monkeypatch.setattr(scheduled_research, "_record_codex_search_failure", lambda *_args, **_kwargs: None)

    def fail_search(*_args, **_kwargs):
        raise ValueError(search_error)

    def forbidden(*_args, **_kwargs):
        pytest.fail("scheduled search failures must not be relabeled with category-feed evidence")

    monkeypatch.setattr(scheduled_research, "gather_with_codex_search", fail_search)
    monkeypatch.setattr(scheduled_research, "gather", forbidden)
    preflight = {
        "local_status": "not_found", "draft_import_allowed": True,
        "automation_execution": {"invocation": invocation},
    }

    with pytest.raises(ValueError, match="scheduled_codex_search_unavailable"):
        scheduled_research.run_authorized_research(
            automation_id="automation-8", category="economy",
            topic="Vietnam's recent economic developments", preflight=preflight,
        )


def test_manual_codex_search_package_is_bound_to_manual_run_id(monkeypatch):
    from woori import codex_runner

    manual_run_id = "codex-manual:automation-8:12345678-1234-5678-1234-567812345678"
    result = {
        "title": "Agency notice on the filing deadline",
        "publisher": "Example Agency",
        "url": "https://example.gov/news/deadline",
        "published_at": "2026-11-04",
        "event_date": None,
        "evidence_excerpt": "The agency published a notice about the filing deadline.",
    }
    snippet = "Published November 4, 2026. The agency published a notice about the filing deadline."

    def fake_execute(*_args, **kwargs):
        assert kwargs["enable_search"] is True
        assert kwargs["require_web_research"] is True
        return {"sources": [result]}, {
            "model": "gpt-6-luna", "web_search_count": 1, "execution_id": "manual-search-1",
            "opened_urls": {result["url"]: "2026-11-05T00:59:00+00:00"},
            "searched_sources": [{"url": result["url"], "title": result["title"],
                                  "domain": "example.gov", "snippet": snippet}],
        }

    monkeypatch.setattr(codex_runner, "execute", fake_execute)
    package = scheduled_research.gather_manual_with_codex_search(
        "general", "the filing deadline", manual_run_id=manual_run_id,
        now=datetime(2026, 11, 5, 1, tzinfo=UTC),
    )
    assert package["schema_version"] == "manual-research-package/1.0"
    assert package["manual_run_id"] == manual_run_id
    assert "occurrence_id" not in package
    assert package["status"] == "evidence_available"
    assert package["sources"][0]["url"] == result["url"]
    assert package["sources"][0]["evidence_excerpt"] == result["evidence_excerpt"]


def test_fixed_rss_fallback_supports_manual_run_identity(monkeypatch):
    now = datetime(2026, 11, 5, 1, tzinfo=UTC)
    published = (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    feed = (
        f"<rss><channel><item><title>Congressional policy notice</title>"
        f"<link>https://www.whitehouse.gov/releases/2026/11/congressional-policy-notice/</link>"
        f"<pubDate>{published}</pubDate><description>Notice summary</description></item></channel></rss>"
    ).encode()
    body = b"<html><main><h1>Congressional policy notice</h1><p>" + (
        b"The notice describes the documented measure and its stated timing. " * 4
    ) + b"</p></main></html>"
    monkeypatch.setattr(
        scheduled_research, "_fetch",
        lambda _provider, url, **_kwargs: feed if url.endswith("/news/feed/") else body,
    )
    manual_run_id = "codex-manual:automation-8:12345678-1234-5678-1234-567812345678"
    package = scheduled_research.gather(
        "politics", "the latest White House notice", manual_run_id=manual_run_id, now=now,
    )
    assert package["schema_version"] == "manual-research-package/1.0"
    assert package["manual_run_id"] == manual_run_id
    assert "occurrence_id" not in package
    assert package["status"] == "evidence_available"
    assert package["sources"][0]["semantic_review"] == "required"


def test_manual_research_requires_exact_run_now_preflight_and_preserves_remote_unknown(monkeypatch):
    from uuid import uuid4

    from woori import automation_authoring_contract

    session_id = str(uuid4())
    manual_run_id = f"codex-manual:automation-8:{uuid4()}"
    invocation = {
        "automation_id": "automation-8", "execution_mode": "manual",
        "trigger": "automation_cron_run_now", "session_id": session_id,
        "manual_run_id": manual_run_id,
        "manual_origin": {
            "execution_mode": "manual", "automation_id": "automation-8",
            "manual_run_id": manual_run_id, "session_id": session_id,
            "turn_trigger": "automation_cron_run_now", "invoked_at": "2026-11-05T10:00:00+09:00",
        },
    }
    contract = automation_authoring_contract.select_authoring_contract(invocation)
    monkeypatch.setattr(automation_invocation, "resolve_current_invocation", lambda *_args, **_kwargs: invocation)
    monkeypatch.setattr(scheduled_research, "gather_manual_with_codex_search", lambda *_args, **kwargs: {
        "status": "evidence_available", "manual_run_id": kwargs["manual_run_id"], "sources": [{"url": "fixed"}],
    })
    monkeypatch.setattr(scheduled_research, "write_package", lambda package, *, automation_id: {
        "status": package["status"], "path": "fixture", "source_count": 1,
    })
    preflight = {
        "status": "unknown", "overall_status": "unknown", "remote_status": "not_checked",
        "local_status": "not_found", "draft_import_allowed": True,
        "automation_execution": {"invocation": invocation, "contract": contract},
    }

    result = scheduled_research.run_manual_authorized_research(
        automation_id="automation-8", category="general", topic="the verified filing update",
        preflight=preflight,
    )
    assert result["execution_mode"] == "manual"
    assert result["manual_run_id"] == manual_run_id
    assert result["overall_status"] == "unknown"
    assert result["remote_status"] == "not_checked"
    with pytest.raises(ValueError, match="local_duplicate_preflight_not_clear"):
        scheduled_research.run_manual_authorized_research(
            automation_id="automation-8", category="general", topic="the verified filing update",
            preflight={**preflight, "local_status": "unknown", "draft_import_allowed": False},
        )
    with pytest.raises(ValueError, match="preflight_invocation_mismatch"):
        scheduled_research.run_manual_authorized_research(
            automation_id="automation-8", category="general", topic="the verified filing update",
            preflight={**preflight, "automation_execution": {"invocation": {**invocation, "manual_run_id": "wrong"}, "contract": contract}},
        )


def test_manual_research_package_is_immutable_and_audited(monkeypatch, tmp_path):
    events = []

    class FakeConnection:
        def execute(self, query, params):
            events.append((query, params))

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(scheduled_research, "connection", fake_connection)
    monkeypatch.setattr(scheduled_research, "PACKAGE_DIR", tmp_path)
    manual_run_id = "codex-manual:automation-8:12345678-1234-5678-1234-567812345678"
    package = {"schema_version": "manual-research-package/1.0", "manual_run_id": manual_run_id,
               "category": "general", "status": "evidence_available", "sources": [{"title": "A"}]}
    result = scheduled_research.write_package(package, automation_id="automation-8")
    path = tmp_path / "automation-8-manual-12345678-1234-5678-1234-567812345678.research.json"
    original = path.read_bytes()
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    assert events[0][1][0] == "research.manual_package.saved"
    assert scheduled_research.write_package(package, automation_id="automation-8")["sha256"] == result["sha256"]
    with pytest.raises(ValueError, match="manual_research_package_conflict"):
        scheduled_research.write_package({**package, "topic": "different"}, automation_id="automation-8")
    assert path.read_bytes() == original
