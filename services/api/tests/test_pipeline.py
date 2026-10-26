import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from woori import pipeline
from woori.ai import EngineFailure, LocalProvider, MockProvider, provider
from woori.config import settings
from woori.db import connection
from woori.main import app


class HiddenHeaders(dict[str, str]):
    def __repr__(self) -> str:
        return "<redacted auth headers>"


@pytest.fixture
def lab(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, TestClient, dict[str, str]]]:
    with connection() as conn, conn.transaction(force_rollback=True):

        @contextmanager
        def shared() -> Iterator[Any]:
            with conn.transaction():
                yield conn

        for module in ("pipeline", "research_routes", "main", "multilingual"):
            monkeypatch.setattr("woori." + module + ".connection", shared)
        monkeypatch.setattr(pipeline, "resources_ok", lambda _: True)
        conn.execute("UPDATE generation_settings SET daily_limit=50,provider='mock',model='mock-v1',engine='ollama'")
        conn.execute("UPDATE keyword_candidates SET status='excluded'")
        with TestClient(app) as api:
            yield conn, api, HiddenHeaders(Authorization="Bearer " + settings().admin_token)


def topic(lab: Any, *, reviewed: bool = True) -> tuple[Any, list[Any]]:
    conn, api, h = lab
    profiles = conn.execute(
        "SELECT p.id FROM language_profiles p JOIN languages l ON l.code=p.language_code WHERE l.active ORDER BY p.language_code"
    ).fetchall()
    category = conn.execute("SELECT id FROM categories WHERE slug='finance'").fetchone()["id"]
    request = {
        "profile_id": str(profiles[0]["id"]),
        "category_id": str(category),
        "keyword": "Synthetic research " + uuid.uuid4().hex,
        "search_intent": "Synthetic informational test",
        "collection_source": "Manual synthetic fixture",
        "rationale": "Pipeline verification only, no real financial claims",
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    r = api.post("/admin/research/keywords", headers=h, json=request)
    assert r.status_code == 201, r.text
    keyword = r.json()["id"]
    assert r.json()["search_volume"] is None and r.json()["cpc"] is None
    assert api.post("/admin/research/keywords", headers=h, json=request).status_code == 409
    assert (
        api.put(
            "/admin/research/keywords/" + keyword, headers=h, json={"status": "selected"}
        ).status_code
        == 200
    )
    source = api.post(
        "/admin/research/sources",
        headers=h,
        json={
            "keyword_id": keyword,
            "url": "https://example.com/" + uuid.uuid4().hex,
            "source_name": "Synthetic fixture",
            "evidence": "Synthetic test evidence "
            + uuid.uuid4().hex
            + ". Not a statement of real world facts.",
            "reliability_reason": "Explicitly synthetic controlled fixture only",
            "rights": "Authored test fixture, no third party text",
            "access_policy": "Manual registration; no network fetch or scraping performed",
            "valid_until": request["expires_at"],
            "is_primary": True,
        },
    )
    assert source.status_code == 201, source.text
    if reviewed:
        review = api.post(
            "/admin/research/sources/" + source.json()["id"] + "/reviews",
            headers=h,
            json={
                "approved": True,
                "reason": "Verified synthetic fixture only; not publishable",
                "reviewer": "Mock tester",
            },
        )
        assert review.status_code == 201, review.text
    return keyword, [p["id"] for p in profiles]


def run_job(lab: Any, keyword: str) -> dict[str, Any]:
    _, api, h = lab
    payload = {"keyword_id": keyword, "idempotency_key": "test-" + uuid.uuid4().hex}
    r = api.post("/admin/research/jobs", headers=h, json=payload)
    assert r.status_code == 201, r.text
    assert api.post("/admin/research/jobs", headers=h, json=payload).json()["id"] == r.json()["id"]
    assert pipeline.tick()
    return r.json()


def test_failed_local_quality_gate_is_always_quality_held() -> None:
    checks = {"structural_pass": True, "grounding": {"rule_pass": False}}
    assert pipeline.draft_state("local", False, checks) == "quality_held"
    assert pipeline.draft_state("local", True, {"structural_pass": True, "grounding": {"rule_pass": True}}) == "quality_held"
    assert pipeline.draft_state("local", False, {"structural_pass": True, "grounding": {"rule_pass": True}}) == "human_review_required"


def test_pipeline_n_languages_versions_and_audit(lab: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, api, h = lab
    keyword, profiles = topic(lab)
    job = run_job(lab, keyword)
    rows = conn.execute("SELECT * FROM generation_results WHERE run_id=%s", (job["id"],)).fetchall()
    assert len(rows) == len(profiles) == 4
    assert all(
        r["state"] == "mock_draft" and not r["result_metadata"]["quality"]["publish_ready"]
        for r in rows
    )
    assert (
        conn.execute("SELECT status FROM job_runs WHERE id=%s", (job["id"],)).fetchone()["status"]
        == "succeeded"
    )
    old_ids = {r["content_version_id"] for r in rows}
    original = MockProvider.generate

    def revised(self: MockProvider, context: dict[str, Any], policy: dict[str, Any]) -> Any:
        draft = original(self, context, policy)
        draft.body += (
            "\n## Revision\n" + "Reviewed synthetic revision context and commentary. " * 40
        )
        return draft

    monkeypatch.setattr(MockProvider, "generate", revised)
    run_job(lab, keyword)
    versions = conn.execute(
        "SELECT * FROM content_versions WHERE group_id=(SELECT group_id FROM keyword_candidates WHERE id=%s)",
        (keyword,),
    ).fetchall()
    assert len(versions) == 8 and old_ids.issubset({v["id"] for v in versions})
    assert {v["version"] for v in versions} == {1, 2}
    for sql in (
        "UPDATE audit_events SET payload=payload",
        "DELETE FROM generation_results",
        "UPDATE research_sources SET evidence=evidence",
    ):
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute(sql)
    events = conn.execute(
        "SELECT event_type FROM audit_events WHERE run_id=%s", (job["id"],)
    ).fetchall()
    assert "research.completed" in {r["event_type"] for r in events}
    assert api.get("/admin/research/state").status_code == 401
    assert api.get("/admin/research/state", headers=h).status_code == 200


def test_evidence_block_and_duplicate_generation(lab: Any) -> None:
    conn, _api, _h = lab
    keyword, _ = topic(lab, reviewed=False)
    first = run_job(lab, keyword)
    assert (
        conn.execute("SELECT error_type FROM job_runs WHERE id=%s", (first["id"],)).fetchone()[
            "error_type"
        ]
        == "insufficient_reviewed_evidence"
    )
    assert not conn.execute(
        "SELECT 1 FROM generation_results WHERE run_id=%s", (first["id"],)
    ).fetchone()
    keyword, _ = topic(lab)
    run_job(lab, keyword)
    second = run_job(lab, keyword)
    assert (
        conn.execute("SELECT error_type FROM job_runs WHERE id=%s", (second["id"],)).fetchone()[
            "error_type"
        ]
        == "duplicate_content"
    )


def test_dynamic_language_and_unsupported_local(lab: Any) -> None:
    conn, api, h = lab
    code = "es-x-" + uuid.uuid4().hex[:8]
    assert (
        api.post(
            "/admin/config/languages",
            headers=h,
            json={"code": code, "display_name": "Synthetic Spanish"},
        ).status_code
        == 201
    )
    keyword, _profiles = topic(lab)
    job = run_job(lab, keyword)
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM generation_results WHERE run_id=%s", (job["id"],)
        ).fetchone()["n"]
        == 5
    )
    with pytest.raises(EngineFailure, match="language_support_unverified"):
        LocalProvider().generate({}, {"language_verified": False})
    profile = conn.execute("SELECT * FROM generation_settings LIMIT 1").fetchone()
    payload = {
        k: profile[k]
        for k in (
            "provider",
            "model",
            "enabled",
            "language_verified",
            "verification_reason",
            "daily_limit",
            "threads",
            "timeout_seconds",
        )
    }
    payload["prompt_id"] = str(profile["prompt_id"])
    payload["provider"] = "paid"
    assert (
        api.put(
            "/admin/research/settings/" + str(profile["profile_id"]), headers=h, json=payload
        ).status_code
        == 422
    )


def test_retry_recovery_pause_scheduler(lab: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, api, h = lab
    keyword, _ = topic(lab)
    old = MockProvider.generate

    def timeout(self: MockProvider, context: dict[str, Any], policy: dict[str, Any]) -> Any:
        raise EngineFailure("local_model_unavailable", True)

    monkeypatch.setattr(MockProvider, "generate", timeout)
    job = run_job(lab, keyword)
    r = conn.execute("SELECT * FROM job_runs WHERE id=%s", (job["id"],)).fetchone()
    assert r["status"] == "queued" and r["attempts"] == 1
    assert (
        api.post(
            "/admin/research/jobs/" + job["id"] + "/action", headers=h, json={"action": "pause"}
        ).status_code
        == 200
    )
    assert pipeline.tick() is False
    api.post("/admin/research/jobs/" + job["id"] + "/action", headers=h, json={"action": "resume"})
    conn.execute(
        "UPDATE job_runs SET status='running',lease_until=now()-interval '1 second' WHERE id=%s",
        (job["id"],),
    )
    conn.execute("UPDATE job_runs SET available_at=now() WHERE id=%s", (job["id"],))
    monkeypatch.setattr(MockProvider, "generate", old)
    assert pipeline.tick()
    assert (
        conn.execute("SELECT status FROM job_runs WHERE id=%s", (job["id"],)).fetchone()["status"]
        == "succeeded"
    )
    assert conn.execute(
        "SELECT 1 FROM generation_attempts WHERE run_id=%s AND event='recovered'", (job["id"],)
    ).fetchone()
    next_keyword, _ = topic(lab)
    k = conn.execute("SELECT * FROM keyword_candidates WHERE id=%s", (next_keyword,)).fetchone()
    r = api.post(
        "/admin/research/schedules",
        headers=h,
        json={
            "category_id": str(k["category_id"]),
            "profile_id": str(k["profile_id"]),
            "active": True,
            "schedule_cron": "0 9 * * *",
            "timezone": "Asia/Seoul",
            "quantity": 1,
        },
    )
    assert r.status_code == 201, r.text
    conn.execute(
        "UPDATE research_schedules SET next_run_at=now()-interval '1 second' WHERE id=%s",
        (r.json()["id"],),
    )
    pipeline.schedule_tick()
    pipeline.schedule_tick()
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM generation_jobs WHERE keyword_id=%s", (next_keyword,)
        ).fetchone()["n"]
        == 1
    )


@pytest.mark.parametrize("name", ["openai", "anthropic", "paid", "", "unknown"])
def test_paid_provider_closed(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Network must never be called")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    with pytest.raises(EngineFailure, match="paid_or_unknown_provider_blocked"):
        provider(name)


def test_partial_retry_skips_saved_targets_and_fences(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _, _ = lab
    keyword, _ = topic(lab)
    original = MockProvider.generate
    calls = 0

    def flaky(self: MockProvider, context: dict[str, Any], policy: dict[str, Any]) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise EngineFailure("temporary_model_failure", True)
        return original(self, context, policy)

    monkeypatch.setattr(MockProvider, "generate", flaky)
    job = run_job(lab, keyword)
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM generation_results WHERE run_id=%s", (job["id"],)
        ).fetchone()["n"]
        == 1
    )
    conn.execute("UPDATE job_runs SET available_at=now() WHERE id=%s", (job["id"],))
    assert pipeline.tick()
    assert calls == 5
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM generation_results WHERE run_id=%s", (job["id"],)
        ).fetchone()["n"]
        == 4
    )


def test_evidence_revocation_and_resources(lab: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, api, h = lab
    keyword, _ = topic(lab)
    source = conn.execute(
        "SELECT id FROM research_sources WHERE keyword_id=%s", (keyword,)
    ).fetchone()["id"]
    api.post(
        "/admin/research/sources/" + str(source) + "/reviews",
        headers=h,
        json={
            "approved": False,
            "reason": "Evidence was retracted; do not generate",
            "reviewer": "Reviewer",
        },
    )
    job = run_job(lab, keyword)
    assert (
        conn.execute("SELECT error_type FROM job_runs WHERE id=%s", (job["id"],)).fetchone()[
            "error_type"
        ]
        == "insufficient_reviewed_evidence"
    )
    keyword, _ = topic(lab)
    r = api.post(
        "/admin/research/jobs",
        headers=h,
        json={"keyword_id": keyword, "idempotency_key": uuid.uuid4().hex},
    )
    monkeypatch.setattr(pipeline, "resources_ok", lambda _: False)
    assert not pipeline.tick()
    assert (
        conn.execute("SELECT attempts FROM job_runs WHERE id=%s", (r.json()["id"],)).fetchone()[
            "attempts"
        ]
        == 0
    )


def test_local_wire_protocol_mock_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    seen = []
    client_class = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "tiny:latest", "size": 1000000, "details": {"format": "gguf"}}
                    ]
                },
            )
        payload = json.loads(request.content)
        assert payload["options"]["num_gpu"] == 0 and payload["options"]["num_thread"] == 2
        assert payload["stream"] is False and payload["keep_alive"] == 0
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "title": "Test title",
                        "body": "A synthetic body sufficiently long for the protocol test.",
                        "summary": "A synthetic summary for testing",
                        "keywords": ["test"],
                        "source_ids": ["fixture"],
                    }
                )
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handler), **kw)
    )
    result = LocalProvider().generate(
        {"instructions": "Use only test data"},
        {"language_verified": True, "model": "tiny:latest", "timeout_seconds": 5, "threads": 2},
    )
    assert result.title == "Test title" and len(seen) == 2
    with pytest.raises(EngineFailure, match="cloud_or_invalid_model_blocked"):
        LocalProvider().generate({}, {"language_verified": True, "model": "paid:cloud"})
    assert len(seen) == 2


def test_stale_lease_cannot_commit(lab: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, _, _ = lab
    keyword, _ = topic(lab)
    original = MockProvider.generate

    def lose_lease(self: MockProvider, context: dict[str, Any], policy: dict[str, Any]) -> Any:
        conn.execute(
            "UPDATE job_runs SET attempts=attempts+1 WHERE task_kind='content' AND status='running'"
        )
        return original(self, context, policy)

    monkeypatch.setattr(MockProvider, "generate", lose_lease)
    job = run_job(lab, keyword)
    assert not conn.execute(
        "SELECT 1 FROM generation_results WHERE run_id=%s", (job["id"],)
    ).fetchone()
    assert (
        conn.execute("SELECT attempts FROM job_runs WHERE id=%s", (job["id"],)).fetchone()[
            "attempts"
        ]
        == 2
    )
    conn.execute(
        "UPDATE job_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (job["id"],)
    )
    monkeypatch.setattr(MockProvider, "generate", original)
    assert pipeline.tick()
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM generation_results WHERE run_id=%s", (job["id"],)
        ).fetchone()["n"]
        == 4
    )


def test_disabled_profile_blocks_queued_job(lab: Any) -> None:
    conn, api, h = lab
    keyword, _ = topic(lab)
    r = api.post(
        "/admin/research/jobs",
        headers=h,
        json={"keyword_id": keyword, "idempotency_key": uuid.uuid4().hex},
    )
    conn.execute(
        "UPDATE generation_settings SET enabled=false WHERE profile_id=(SELECT profile_id FROM keyword_candidates WHERE id=%s)",
        (keyword,),
    )
    assert pipeline.tick()
    assert (
        conn.execute("SELECT error_type FROM job_runs WHERE id=%s", (r.json()["id"],)).fetchone()[
            "error_type"
        ]
        == "profile_processing_disabled"
    )
    assert not conn.execute(
        "SELECT 1 FROM generation_results WHERE run_id=%s", (r.json()["id"],)
    ).fetchone()
