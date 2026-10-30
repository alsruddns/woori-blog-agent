from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from test_pipeline import lab as shared_lab
from woori import external_policy, trends
from woori.trends import ALLOWED_GEOS, parse_feed

lab = shared_lab


@pytest.mark.parametrize(('minutes','expected'),[(5,'0.08'),(6,'0.1'),(10,'0.17'),
    (15,'0.25'),(20,'0.33'),(25,'0.42'),(30,'0.5'),(60,'1')])
def test_trend_window_parameter_is_decimal_not_a_verified_filter(minutes,expected):
    assert trends.minutes_to_hours_parameter(minutes)==expected


@pytest.mark.parametrize('minutes',[0,61,-1,True,1.5])
def test_trend_window_parameter_rejects_invalid_input(minutes):
    with pytest.raises(ValueError):trends.minutes_to_hours_parameter(minutes)


def test_google_trends_feed_preserves_source_fields_without_inventing_rank() -> None:
    raw = b"""<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
      <lastBuildDate>Tue, 27 Oct 2026 08:00:00 GMT</lastBuildDate>
      <item><title>Sample query</title><pubDate>Tue, 27 Oct 2026 07:00:00 GMT</pubDate>
      <ht:approx_traffic>5,000+</ht:approx_traffic><link>https://trends.google.com/trending?geo=KR</link></item>
    </channel></rss>"""
    result = parse_feed(raw, "KR", datetime(2026, 10, 27, 9, tzinfo=UTC))
    assert len(result["items"]) == 1
    row = result["items"][0]
    assert row["query"] == "Sample query"
    assert row["source_rank"] is None
    assert row["source_volume_label"] == "5,000+"
    assert row["source_volume_lower_bound"] == 5000
    assert row["source_volume_period"] is None
    assert row["related_terms"] == []
    assert row["source_updated_at"] == datetime(2026, 10, 27, 8, tzinfo=UTC)


@pytest.mark.parametrize(("label", "expected"), [
    ("100+", 100), ("1,000+", 1000), ("1.2K+", 1200),
    ("2M+", 2_000_000), (None, None), ("about 1,000", None), ("0+", 0),
])
def test_approx_traffic_lower_bound_is_conservative(label: str | None, expected: int | None) -> None:
    assert trends.parse_approx_traffic(label) == expected


def test_approx_traffic_raw_source_string_is_preserved_and_missing_is_null() -> None:
    raw = b"""<rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
      <item><title>Whitespace</title><ht:approx_traffic> 1,000+ </ht:approx_traffic></item>
      <item><title>Missing</title></item>
    </channel></rss>"""
    rows = parse_feed(raw, "KR")["items"]
    assert rows[0]["source_volume_label"] == " 1,000+ "
    assert rows[0]["source_volume_lower_bound"] == 1000
    assert rows[1]["source_volume_label"] is None
    assert rows[1]["source_volume_lower_bound"] is None


def test_hourly_scheduler_spreads_regions_and_respects_global_spacing() -> None:
    from datetime import timedelta

    now = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    assert trends.choose_due_geo({}, None, now) == "AU"
    attempts = {"HK": now}
    assert trends.choose_due_geo(attempts, now, now + timedelta(minutes=4)) is None
    assert trends.choose_due_geo(attempts, now, now + timedelta(minutes=5)) == "AU"
    spread = {"AU": now, "CA": now + timedelta(minutes=5)}
    assert trends.choose_due_geo(spread, now + timedelta(minutes=5), now + timedelta(hours=1)) == "GB"
    full = {geo: now - timedelta(minutes=5) for geo in trends.ALLOWED_GEOS}
    assert trends.choose_due_geo(full, now - timedelta(minutes=5), now) is None


@pytest.mark.parametrize("geo", ["CN", "KR/../US", "", "ZZ"])
def test_google_trends_rejects_unconfigured_geographies(geo: str) -> None:
    with pytest.raises(ValueError, match="trend_geo_not_allowlisted"):
        parse_feed(b"<rss><channel/></rss>", geo)


def test_google_trends_allowlist_has_eleven_regions_and_supports_full_cycle_under_quota() -> None:
    from datetime import timedelta

    assert trends.ALLOWED_GEOS == {"KR", "US", "JP", "TW", "HK", "SG", "GB", "CA", "AU", "IN", "PH"}
    now = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    attempts: dict[str, datetime] = {}
    seen: list[str] = []
    for offset in range(0, 55, 5):
        current = now + timedelta(minutes=offset)
        geo = trends.choose_due_geo(attempts, current - timedelta(minutes=5) if attempts else None, current)
        assert geo is not None
        seen.append(geo)
        attempts[geo] = current
    assert set(seen) == trends.ALLOWED_GEOS
    assert len(seen) == 11


def test_google_trends_feed_rejects_entities_and_oversize() -> None:
    with pytest.raises(ValueError, match="unsafe_or_too_large"):
        parse_feed(b"<!DOCTYPE rss [<!ENTITY x 'bad'>]><rss/>", "US")
    with pytest.raises(ValueError, match="unsafe_or_too_large"):
        parse_feed(b" " * (1024 * 1024 + 1), "US")


def test_trends_external_gate_allows_only_fixed_rss_geos_and_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(external_policy, "billing_credential_names", list)
    monkeypatch.setattr(external_policy, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(external_policy, "_reserve_google_trends_call", lambda *args: None)
    for geo in ALLOWED_GEOS:
        monkeypatch.setattr(external_policy, "_windows", {})
        external_policy._authorize(
            "google_trends_rss",
            "trend_collection",
            httpx.Request("GET", f"https://trends.google.com/trending/rss?geo={geo}"),
        )
    for request in (
        httpx.Request("GET", "https://trends.google.com/trending/rss?geo=CN"),
        httpx.Request("POST", "https://trends.google.com/trending/rss?geo=KR"),
        httpx.Request("GET", "https://trends.google.com/trending/api?geo=KR"),
        httpx.Request("GET", "https://trends.google.com/trending/rss?geo=KR&hours=1"),
        httpx.Request("GET", "https://trends.google.com/trending/rss?geo=KR&hours=2"),
    ):
        monkeypatch.setattr(external_policy, "_windows", {})
        with pytest.raises(external_policy.ExternalCallBlocked):
            external_policy._authorize("google_trends_rss", "trend_collection", request)


def test_google_trends_external_spacing_and_rolling_cap_are_durable_in_isolated_db(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from woori import db

    conn, _, _ = lab

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    monkeypatch.setattr(db, "connection", shared_connection)
    assert external_policy._reserve_google_trends_call(
        "trends.google.com", "GET", "trend_collection"
    ) is None
    assert external_policy._reserve_google_trends_call(
        "trends.google.com", "GET", "trend_collection"
    ) == "provider_minimum_spacing"
    conn.execute(
        """INSERT INTO audit_events(event_type,payload,created_at)
        SELECT 'external.call.started',jsonb_build_object('provider','google_trends_rss'),now()-interval '6 minutes'
        FROM generate_series(1,11)"""
    )
    assert external_policy._reserve_google_trends_call(
        "trends.google.com", "GET", "trend_collection"
    ) == "durable_free_hourly_call_limit_reached"


def test_hourly_scheduler_starts_on_top_of_hour_and_resumes_without_repeating_slots() -> None:
    from datetime import timedelta

    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)  # 09:00 KST
    assert trends.choose_hourly_geo({}, {}, None, start) == ("AU", "selected")
    assert trends.choose_hourly_geo({}, {}, None, start + timedelta(minutes=5)) == (
        None, "waiting_for_top_of_hour"
    )
    assert trends.choose_hourly_geo({}, {}, None, start + timedelta(minutes=4)) == (
        "AU", "selected"
    )
    assert trends.choose_hourly_geo({}, {}, start, start + timedelta(minutes=4)) == (
        None, "not_due"
    )

    attempts = {geo: None for geo in ALLOWED_GEOS}
    attempts["AU"] = start
    current_hour = {"AU": [{"attempted_at": start, "status": "succeeded", "failure_category": None}]}
    assert trends.choose_hourly_geo(attempts, current_hour, start, start + timedelta(minutes=5)) == (
        "CA", "selected"
    )
    completed = {
        geo: [{"attempted_at": start + timedelta(minutes=index * 5),
               "status": "succeeded", "failure_category": None}]
        for index, geo in enumerate(sorted(ALLOWED_GEOS))
    }
    assert trends.choose_hourly_geo({}, completed, start, start + timedelta(minutes=55)) == (
        None, "hour_sweep_complete"
    )


def test_hourly_scheduler_runs_all_eleven_regions_in_sequential_five_minute_slots() -> None:
    from datetime import timedelta

    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    ordered_geos = sorted(ALLOWED_GEOS)
    attempts = {
        geo: start - timedelta(hours=1) + timedelta(minutes=index * 5)
        for index, geo in enumerate(ordered_geos)
    }
    hour_attempts: dict[str, list[dict[str, Any]]] = {}
    last_global = start - timedelta(minutes=5)
    actual: list[str] = []
    for index in range(11):
        current = start + timedelta(minutes=index * 5)
        selected, decision = trends.choose_hourly_geo(attempts, hour_attempts, last_global, current)
        assert selected == ordered_geos[index]
        assert decision == "selected"
        actual.append(selected)
        attempts[selected] = current
        hour_attempts[selected] = [{"attempted_at": current, "status": "succeeded", "failure_category": None}]
        last_global = current
    assert len(set(actual)) == 11
    assert trends.choose_hourly_geo(attempts, hour_attempts, last_global, start + timedelta(minutes=55)) == (
        None, "hour_sweep_complete"
    )


def test_hourly_scheduler_retries_only_transient_failed_region_once() -> None:
    from datetime import timedelta

    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    failed = {"KR": [{"attempted_at": start, "status": "failed",
                      "failure_category": "trend_feed_network_error"}]}
    assert trends.choose_hourly_geo({}, failed, start, start + timedelta(minutes=5)) == (
        "KR", "selected_retry"
    )
    blocked = {"KR": [{"attempted_at": start, "status": "blocked",
                        "failure_category": "provider_quota_or_rate_limit"}]}
    assert trends.choose_hourly_geo({}, blocked, start, start + timedelta(minutes=5)) == (
        "AU", "selected"
    )

    recent_attempts = {geo: start - timedelta(minutes=30) for geo in ALLOWED_GEOS}
    attempted_this_hour = {"AU": [{"attempted_at": start, "status": "succeeded", "failure_category": None}]}
    assert trends.choose_hourly_geo(
        recent_attempts, attempted_this_hour, start, start + timedelta(minutes=5)
    ) == (None, "waiting_for_region_interval")


def test_trend_collection_persists_actual_pipeline_shape_in_isolated_db(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, api, headers = lab
    prior_attempts = conn.execute("SELECT count(*) AS n FROM trend_collection_attempts").fetchone()[
        "n"
    ]

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    raw = b"""<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
      <item><title>Fixture trend</title><ht:approx_traffic>1,000+</ht:approx_traffic></item>
    </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://trends.google.com/trending/rss?geo=GB"
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/rss+xml"})

    monkeypatch.setattr(trends, "connection", shared_connection)
    monkeypatch.setattr(
        trends,
        "external_client",
        lambda *args, **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout", 15)
        ),
    )
    response = api.post("/admin/research/trends/collect", headers=headers, json={"geo": "GB"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    assert result["http_status"] == 200
    assert result["item_count"] == 1
    assert result["rank_available"] is False
    assert (
        conn.execute("SELECT count(*) AS n FROM trend_collection_attempts").fetchone()["n"]
        == prior_attempts + 1
    )
    row = conn.execute(
        "SELECT geo,query,source_rank,source_volume_label FROM trend_observations WHERE run_id=%s",
        (UUID(result["run_id"]),),
    ).fetchone()
    assert dict(row) == {
        "geo": "GB",
        "query": "Fixture trend",
        "source_rank": None,
        "source_volume_label": "1,000+",
    }
    volume_columns = {item["column_name"] for item in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='trend_observations'"
    ).fetchall()}
    if "source_volume_lower_bound" in volume_columns:
        assert conn.execute(
            "SELECT source_volume_lower_bound,source_volume_period FROM trend_observations WHERE run_id=%s",
            (UUID(result["run_id"]),),
        ).fetchone() == {"source_volume_lower_bound": 1000, "source_volume_period": None}
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='trend.collection.completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event["payload"]["collection_run_id"] == result["run_id"]
    run = conn.execute(
        "SELECT http_status,status FROM trend_collection_runs WHERE id=%s",
        (UUID(result["run_id"]),),
    ).fetchone()
    assert dict(run) == {"http_status": 200, "status": "succeeded"}
    with pytest.raises(psycopg.errors.RaiseException, match="(?i)append-only"), conn.transaction():
        conn.execute(
            "UPDATE trend_observations SET query='changed' WHERE run_id=%s",
            (UUID(result["run_id"]),),
        )


def test_observation_summary_tracks_new_continuing_and_period_unknown(lab: Any) -> None:
    conn, _, _ = lab
    query = "Summary fixture " + uuid4().hex
    base = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    source_hash = "a" * 64
    for index, collected_at in enumerate((base, base + timedelta(minutes=5))):
        run_id = uuid4()
        conn.execute(
            """INSERT INTO trend_collection_runs
            (id,provider,geo,status,item_count,response_sha256,http_status,started_at,finished_at)
            VALUES (%s,'google_trends_rss','KR','succeeded',1,%s,200,%s,%s)""",
            (run_id, source_hash, collected_at, collected_at),
        )
        conn.execute(
            """INSERT INTO trend_observations
            (run_id,geo,platform,query,source_volume_label,trend_started_at,source_updated_at,
             collected_at,source_url,response_sha256)
            VALUES (%s,'KR','google_trends',%s,'1,000+',%s,%s,%s,%s,%s)""",
            (run_id, query, collected_at, collected_at, collected_at,
             "https://trends.google.com/trending/rss?geo=KR", source_hash),
        )
    summaries = trends.observation_summaries(conn)
    summary = next(row for row in summaries if row["query"] == query)
    assert summary["observation_status"] == "continuing"
    assert summary["observation_count"] == 2
    assert summary["source_volume_lower_bound"] == 1000
    assert summary["source_volume_period"] is None
    assert summary["traffic_change_status"] == "period_unknown"
    assert summary["research_status"] == "not_researched"


def test_direct_trend_collection_obeys_global_minimum_spacing(
    lab: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, api, headers = lab
    prior = conn.execute(
        "SELECT count(*) AS n FROM trend_collection_attempts"
    ).fetchone()["n"]
    conn.execute(
        "INSERT INTO trend_collection_attempts(id,provider,geo,attempted_at) VALUES (%s,%s,%s,now())",
        (UUID("00000000-0000-4000-8000-000000000021"), "google_trends_rss", "KR"),
    )

    @contextmanager
    def shared_connection() -> Any:
        with conn.transaction():
            yield conn

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("external request must be blocked by durable pacing")

    monkeypatch.setattr(trends, "connection", shared_connection)
    monkeypatch.setattr(trends, "external_client", forbidden)
    response = api.post("/admin/research/trends/collect", headers=headers, json={"geo": "GB"})
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["failure_category"] == "global_minimum_spacing"
    assert conn.execute("SELECT count(*) AS n FROM trend_collection_attempts").fetchone()["n"] == prior + 1
    event = conn.execute(
        "SELECT payload FROM audit_events WHERE event_type='trend.collection.pacing_blocked' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event["payload"]["geo"] == "GB"
