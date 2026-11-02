import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_pipeline import lab as shared_lab
from test_trend_editorial import observation
from woori import automation_controls as controls
from woori import editorial_intelligence, trend_editorial, trends
from woori import research_stages as stages
from woori.db import bounded_stage_sql
from woori.db import connection as independent_connection

lab = shared_lab


def test_current_handoff_admission_continues_without_recomputing_scores(monkeypatch):
    from woori import keyword_jobs

    calls = []
    monkeypatch.setattr(trend_editorial, "expire_pending", lambda: calls.append("expire"))
    monkeypatch.setattr(trend_editorial, "dispatch", lambda: calls.append("dispatch"))
    monkeypatch.setattr(keyword_jobs, "tick", lambda **kw: calls.append(("admit", kw)))
    monkeypatch.setattr(
        editorial_intelligence,
        "assess_current",
        lambda *_: pytest.fail("admission must not rescore"),
    )
    stages.authoring_tick()
    stages.authoring_tick()
    assert calls == ["expire", "dispatch", ("admit", {"import_results": False})] * 2


@pytest.fixture
def lanes(lab, monkeypatch):
    conn, api, headers = lab

    @contextmanager
    def shared():
        with conn.transaction():
            yield conn

    for module in (stages, trends, trend_editorial, editorial_intelligence, controls):
        monkeypatch.setattr(module, "connection", shared)
    return conn, api, headers


def test_stage_cache_and_checkpoint_recovery(lanes):
    conn, _, _ = lanes
    scope = uuid4().hex

    def interrupted(job):
        stages.progress(job, "scores_saved", 20, 0, details={"scores": {"selected": 20}})
        raise RuntimeError("private failure text must not enter audit")

    first = stages.execute("topic_evaluation", scope, interrupted)
    assert first["status"] == "failed"
    row = conn.execute(
        "SELECT * FROM research_stage_runs WHERE id=%s", (first["job_id"],)
    ).fetchone()
    assert (
        row["checkpoint"] == "scores_saved"
        and row["processed"] == 20
        and row["error_category"] == "RuntimeError"
    )
    assert row["result"]["scores"] == {"selected": 20}
    assert (
        stages.execute("topic_evaluation", scope, lambda _: pytest.fail("cooldown"))["status"]
        == "retry_wait"
    )
    conn.execute(
        "UPDATE research_stage_runs SET completed_at=now()-interval '2 minutes' WHERE id=%s",
        (first["job_id"],),
    )

    def resume(job):
        saved = conn.execute(
            "SELECT checkpoint FROM research_stage_runs WHERE id=%s", (job,)
        ).fetchone()
        assert saved["checkpoint"] == "scores_saved"
        return {"resumed": True}

    second = stages.execute("topic_evaluation", scope, resume)
    assert second["job_id"] == first["job_id"] and second["status"] == "completed"
    assert (
        stages.execute("topic_evaluation", scope, lambda _: pytest.fail("completed work repeats"))[
            "status"
        ]
        == "cached"
    )


def test_live_lock_prevents_steal_even_for_old_task(lanes):
    _conn, _, _ = lanes
    scope = uuid4().hex
    key = f"p105:topic_evaluation:{scope}:{stages.VERSION}:0"
    with independent_connection() as other:
        other.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
        assert (
            stages.execute(
                "topic_evaluation", scope, lambda _: pytest.fail("must not steal active lock")
            )["status"]
            == "busy"
        )
        other.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
    assert stages.execute("topic_evaluation", scope, lambda _: {})["status"] == "completed"


def test_exited_owner_resumes_without_process_kill(lanes):
    conn, _, _ = lanes
    scope = uuid4().hex
    conn.execute(
        """INSERT INTO research_stage_runs(stage,scope_key,engine_version,status,owner_pid,checkpoint)
        VALUES('topic_evaluation',%s,%s,'running',999999,'scores_saved')""",
        (scope, stages.VERSION),
    )
    assert stages.execute("topic_evaluation", scope, lambda _: {})["status"] == "completed"
    assert (
        conn.execute(
            "SELECT payload FROM audit_events WHERE event_type='research.stage.started' ORDER BY id DESC LIMIT 1"
        ).fetchone()["payload"]["recovered_after_lock_release"]
        is True
    )


def fake_geo(conn, seen, failed=None):
    def collect(geo):
        seen.append(geo)
        status = "failed" if geo == failed else "succeeded"
        run = conn.execute(
            "INSERT INTO trend_collection_runs(provider,geo,status,item_count) VALUES('google_trends_rss',%s,%s,0) RETURNING id",
            (geo, status),
        ).fetchone()["id"]
        return {
            "status": status,
            "geo": geo,
            "run_id": str(run),
            "http_status": 500 if status == "failed" else 200,
            "item_count": 0,
        }

    return collect


def test_partial_retry_only_failed_region_once(lanes, monkeypatch):
    conn, _, _ = lanes
    seen = []
    monkeypatch.setattr(trends, "_collect_geo", fake_geo(conn, seen, "JP"))
    assert trends.schedule_tick()["status"] == "partial"
    slot = trend_editorial.current_slot()
    conn.execute(
        "UPDATE trend_collection_slots SET updated_at=now()-interval '2 minutes' WHERE geo='JP' AND slot_at=%s",
        (slot,),
    )
    assert trends.schedule_tick()["failures"] == 1
    assert seen.count("JP") == 2 and len(seen) == 12
    conn.execute(
        "UPDATE trend_collection_slots SET updated_at=now()-interval '2 minutes' WHERE geo='JP' AND slot_at=%s",
        (slot,),
    )
    assert trends.schedule_tick()["status"] == "slot_complete"
    assert len(seen) == 12


def test_collector_advances_two_slots_while_evaluation_is_blocked(lanes, monkeypatch):
    conn, _, _ = lanes
    seen = []
    slot = [trend_editorial.current_slot()]
    monkeypatch.setattr(trends, "configured_slot", lambda *_: slot[0])
    monkeypatch.setattr(trends, "_collect_geo", fake_geo(conn, seen))
    stop = threading.Event()
    entered = threading.Event()
    release = threading.Event()

    def slow_evaluation():
        entered.set()
        release.wait(5)

    evaluator = threading.Thread(
        target=stages.lane_loop, args=("topic_evaluation", stop, slow_evaluation, 0.01)
    )
    evaluator.start()
    try:
        assert entered.wait(1)
        first = stages.collection_tick()
        assert first["status"] == "completed"
        slot[0] += timedelta(minutes=10)
        second = stages.collection_tick()
        assert second["status"] == "completed" and first["job_id"] != second["job_id"]
        assert evaluator.is_alive() and len(seen) == 22
        assert stages.collection_tick()["status"] == "cached" and len(seen) == 22
    finally:
        stop.set()
        release.set()
        evaluator.join(2)
    assert not evaluator.is_alive()


def test_off_does_not_start_collection_or_evaluation(lanes, monkeypatch):
    conn, _, _ = lanes
    conn.execute("UPDATE trend_collection_settings SET enabled=false WHERE id=1")
    monkeypatch.setattr(trends, "schedule_tick", lambda **_: pytest.fail("OFF collection"))
    assert stages.collection_tick()["status"] == "disabled"
    assert stages.evaluation_tick()["status"] == "disabled"
    conn.execute("UPDATE trend_collection_settings SET enabled=true WHERE id=1")
    monkeypatch.setattr(trends, "_collect_geo", fake_geo(conn, []))


def test_latest_slot_evaluation_skips_legacy_all_pairs_and_reuses_scores(lanes, monkeypatch):
    conn, _, _ = lanes
    monkeypatch.setattr(trends, "_collect_geo", fake_geo(conn, []))
    assert stages.collection_tick()["status"] == "completed"
    calls = []
    monkeypatch.setattr(
        "woori.topics.build_candidates", lambda **_: pytest.fail("legacy all-pairs must not run")
    )
    monkeypatch.setattr(
        trend_editorial, "reconcile", lambda **_: calls.append("classify") or {"selected": 2}
    )
    monkeypatch.setattr(
        editorial_intelligence,
        "assess_current",
        lambda *_: calls.append("score") or {"selected": 2},
    )
    monkeypatch.setattr(trend_editorial, "queue_selected", lambda: {"created": 0})
    monkeypatch.setattr(trend_editorial, "expire_pending", lambda: 0)
    monkeypatch.setattr(trend_editorial, "dispatch", lambda: {"created": 0})
    assert stages.evaluation_tick()["status"] == "completed"
    assert stages.evaluation_tick()["status"] == "cached"
    assert calls == ["classify", "score"]


def test_sql_wait_limits_are_local_not_global():
    with bounded_stage_sql(), independent_connection() as conn:
        assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "15s"
        assert conn.execute("SHOW lock_timeout").fetchone()["lock_timeout"] == "2s"
    with independent_connection() as conn:
        assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "0"


def test_database_lock_wait_is_bounded_without_cancelling_owner():
    import time

    import psycopg

    key = 105796
    with independent_connection() as owner:
        owner.execute("SELECT pg_advisory_lock(%s)", (key,))
        started = time.monotonic()
        with (
            pytest.raises(psycopg.errors.LockNotAvailable),
            bounded_stage_sql(),
            independent_connection() as waiter,
        ):
            waiter.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        assert time.monotonic() - started < 5
        assert owner.execute("SELECT pg_advisory_unlock(%s) released", (key,)).fetchone()[
            "released"
        ]


def test_slow_rss_stream_hits_wall_budget_without_saving_observations(lanes, monkeypatch):
    from types import SimpleNamespace

    import httpx

    conn, _, _ = lanes
    ticks = iter([0, 31])
    monkeypatch.setattr(trends, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"<rss>"
            pytest.fail("wall budget must close stream before the next chunk")

    def response(request):
        assert request.extensions["timeout"]["read"] == 15
        return httpx.Response(200, stream=SlowStream(), request=request)

    monkeypatch.setattr(
        trends,
        "external_client",
        lambda *a, **kw: httpx.Client(
            transport=httpx.MockTransport(response), timeout=kw["timeout"]
        ),
    )
    before = conn.execute("SELECT count(*) n FROM trend_observations").fetchone()["n"]
    result = trends._collect_geo("KR")
    assert result["status"] == "failed" and result["failure_category"] == "trend_feed_wall_timeout"
    assert conn.execute("SELECT count(*) n FROM trend_observations").fetchone()["n"] == before


def test_monitor_distinguishes_heartbeat_from_stale_collection(lanes):
    conn, api, h = lanes
    conn.execute(
        "INSERT INTO worker_heartbeats(service_name,process_id,status,last_seen_at) VALUES('research_worker',105,'running',now()) ON CONFLICT(service_name) DO UPDATE SET status='running',last_seen_at=now()"
    )
    state = api.get("/admin/research/editorial-intelligence/pipeline", headers=h)
    assert state.status_code == 200, state.text
    assert (
        state.json()["health"] == "collection_delayed"
        and state.json()["heartbeat_is_stage_progress"] is False
    )
    assert api.get("/admin/research/editorial-intelligence/pipeline").status_code == 401


def test_same_engine_different_settings_cache_identity(lanes, monkeypatch):
    from woori import editorial_scoring

    conn, _, _ = lanes
    blog = conn.execute(
        "INSERT INTO blogger_blogs(language_code,url,display_name,active) VALUES('en',%s,'Isolated cache test',true) RETURNING id",
        ("https://" + uuid4().hex + ".blogspot.com",),
    ).fetchone()["id"]
    obs = observation(conn, "software policy launch", geo="US")
    topic = uuid4()
    conn.execute(
        "INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,grouping_method,grouping_confidence,grouping_status) VALUES(%s,%s,'US','software policy launch','single_observation',1,'exact_query_cluster_not_event_confirmed')",
        (topic, uuid4().hex),
    )
    row = {
        "id": topic,
        "observation_id": obs,
        "representative_query": "software policy launch",
        "geo": "US",
        "collected_at": datetime.now(UTC),
        "raw_payload": {},
        "source_volume_lower_bound": 1000,
    }
    first = editorial_intelligence.rank_candidates(conn, [row], blog, datetime.now(UTC))
    weights = editorial_scoring.Weights().model_dump()
    conn.execute(
        "INSERT INTO editorial_selection_settings(weights,effective_slot) VALUES(%s,now()-interval '1 day')",
        (Jsonb(weights),),
    )
    second = editorial_intelligence.rank_candidates(conn, [row], blog, datetime.now(UTC))
    assert first[0]["selection"]["settings_id"] != second[0]["selection"]["settings_id"]
    assert (
        conn.execute(
            "SELECT count(*) n FROM editorial_topic_scores WHERE observation_id=%s", (obs,)
        ).fetchone()["n"]
        == 2
    )
