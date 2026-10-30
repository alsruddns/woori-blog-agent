"""Bounded, allowlisted Google Trends RSS collection; feed sequence is not a rank."""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from psycopg.types.json import Jsonb

from .ai import EngineFailure
from .db import connection
from .external_policy import ExternalCallBlocked, FreeQuotaExceeded, external_run
from .external_policy import client as external_client

PROVIDER = "google_trends_rss"
ENDPOINT = "https://trends.google.com/trending/rss"
ALLOWED_GEOS = {"KR", "US", "JP", "TW", "HK", "SG", "GB", "CA", "AU", "IN", "PH"}
GOOGLE_TRENDS_HELP = "https://support.google.com/trends/answer/3076011?hl=en"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ITEMS = 20
COLLECTION_INTERVAL = timedelta(hours=1)
MIN_REQUEST_SPACING = timedelta(minutes=5)
SCHEDULE_TIMEZONE = ZoneInfo("Asia/Seoul")
SCHEDULE_START_WINDOW = timedelta(minutes=5)
MAX_ATTEMPTS_PER_GEO_HOUR = 2
RETRYABLE_FAILURES = {
    "trend_feed_network_error", "trend_feed_response_limit", "http_500", "http_502",
    "http_503", "http_504",
}
SCHEDULER_LOCK = "google_trends_hourly_scheduler"
NS = {"ht": "https://trends.google.com/trending/rss"}


def minutes_to_hours_parameter(minutes: int) -> str:
    """Serialize a requested window; this does not assert provider support."""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 60:
        raise ValueError("trend_window_minutes_out_of_range")
    value=(Decimal(minutes)/Decimal(60)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
    return format(value.normalize(),'f')


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_approx_traffic(value: str | None) -> int | None:
    """Parse only documented-looking bucket labels; never treat them as exact counts."""
    if not value:
        return None
    label = " ".join(value.split()).upper().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([KMB]?)\+", label)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
    try:
        lower_bound = int(Decimal(match.group(1)) * multiplier)
        return lower_bound if lower_bound <= 9_223_372_036_854_775_807 else None
    except InvalidOperation:
        return None


def parse_feed(content: bytes, geo: str, collected_at: datetime | None = None) -> dict[str, Any]:
    """Parse official RSS fields without synthesizing ranks, terms, or numeric volume."""
    if geo not in ALLOWED_GEOS:
        raise ValueError("trend_geo_not_allowlisted")
    if (
        len(content) > MAX_RESPONSE_BYTES
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("trend_feed_response_unsafe_or_too_large")
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise ValueError("trend_feed_invalid_xml") from None
    channel = root.find("channel")
    if channel is None:
        raise ValueError("trend_feed_channel_missing")
    fetched = collected_at or datetime.now(UTC)
    source_updated = _date(channel.findtext("lastBuildDate")) or _date(channel.findtext("pubDate"))
    rows: list[dict[str, Any]] = []
    for item in channel.findall("item")[:MAX_ITEMS]:
        query = " ".join((item.findtext("title") or "").split())
        if not query or len(query) > 300:
            continue
        traffic = item.findtext("{https://trends.google.com/trending/rss}approx_traffic")
        started = _date(item.findtext("pubDate"))
        rows.append(
            {
                "geo": geo,
                "platform": "google_trends",
                "query": query,
                "source_categories": [c.text for c in item.findall('category') if c.text],
                "source_language": channel.findtext('language'),
                "raw_payload": {'item_xml': ET.tostring(item, encoding='unicode'),
                    'news_items': [{'title': n.findtext('ht:news_item_title', namespaces=NS),
                                    'url': n.findtext('ht:news_item_url', namespaces=NS),
                                    'source': n.findtext('ht:news_item_source', namespaces=NS)}
                                   for n in item.findall('ht:news_item', NS)[:5]]},
                "source_rank": None,
                "source_volume_label": traffic if traffic else None,
                "source_volume_lower_bound": parse_approx_traffic(traffic),
                # Google documents bucketed traffic for a selected window, but the
                # RSS export's default window and an `hours` query parameter are
                # not specified. Keep period NULL until that basis is verified.
                "source_volume_period": None,
                "trend_started_at": started,
                "source_updated_at": source_updated,
                "collected_at": fetched,
                "related_terms": [],
                "source_url": f"{ENDPOINT}?geo={geo}",
            }
        )
    return {
        "source_updated_at": source_updated,
        "items": rows,
        "response_sha256": hashlib.sha256(content).hexdigest(),
    }


def _save_failure(
    run_id: Any, geo: str, status: str, reason: str, http_status: int | None = None
) -> dict[str, Any]:
    with connection() as conn:
        conn.execute(
            """INSERT INTO trend_collection_runs
            (id,provider,geo,status,item_count,failure_category,http_status)
            VALUES (%s,%s,%s,%s,0,%s,%s)""",
            (run_id, PROVIDER, geo, status, reason[:100], http_status),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('trend.collection.failed',%s)",
            (
                Jsonb(
                    {
                        "collection_run_id": str(run_id),
                        "provider": PROVIDER,
                        "geo": geo,
                        "status": status,
                        "failure_category": reason[:100],
                        "http_status": http_status,
                    }
                ),
            ),
        )
    return {
        "run_id": str(run_id),
        "geo": geo,
        "status": status,
        "item_count": 0,
        "failure_category": reason[:100],
        "http_status": http_status,
    }


def collect_geo(geo: str) -> dict[str, Any]:
    """Serialize collection; a successful KST geo/hour is never collected twice."""
    if geo not in ALLOWED_GEOS:
        raise ValueError('trend_geo_not_allowlisted')
    bucket=datetime.now(SCHEDULE_TIMEZONE).replace(minute=0,second=0,microsecond=0).astimezone(UTC)
    with connection() as guard:
        locked=guard.execute("SELECT pg_try_advisory_lock(hashtextextended('trend-slot-collection',0)) acquired").fetchone()
        if not locked or not locked['acquired']:return {'status':'busy','geo':geo,'item_count':0}
        try:
            existing=guard.execute("SELECT id,item_count FROM trend_collection_runs WHERE geo=%s AND status='succeeded' AND started_at>=%s AND started_at<%s+interval '1 hour' LIMIT 1",(geo,bucket,bucket)).fetchone()
            if existing:return {'status':'already_collected','geo':geo,'run_id':str(existing['id']),'item_count':existing['item_count'],'new_items':0}
            result=_collect_geo(geo)
            guard.execute('''INSERT INTO trend_collection_slots(geo,slot_at,run_id,result) VALUES(%s,%s,%s,%s)
                ON CONFLICT(geo,slot_at) DO UPDATE SET run_id=EXCLUDED.run_id,result=EXCLUDED.result,updated_at=now()''',
                (geo,bucket,result.get('run_id') if result.get('http_status') is not None else None,
                 Jsonb({k:v.isoformat() if isinstance(v,datetime) else v for k,v in result.items()})))
            return result
        finally:guard.execute("SELECT pg_advisory_unlock(hashtextextended('trend-slot-collection',0))")


def _collect_geo(geo: str) -> dict[str, Any]:
    if geo not in ALLOWED_GEOS:
        raise ValueError("trend_geo_not_allowlisted")
    with connection() as conn:
        schema_row = conn.execute(
            "SELECT to_regclass('public.trend_collection_runs') AS table_name"
        ).fetchone()
        if schema_row is None or not schema_row["table_name"]:
            raise EngineFailure("trend_schema_not_applied")
    run_id = uuid4()
    started = time.monotonic()
    http_status: int | None = None
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('google_trends_rss',0))")
        spacing_row = conn.execute(
            "SELECT max(attempted_at) AS last_attempt FROM trend_collection_attempts"
        ).fetchone()
        last_attempt = spacing_row["last_attempt"] if spacing_row else None
        now = datetime.now(UTC)
        if last_attempt and now - last_attempt < MIN_REQUEST_SPACING:
            next_eligible_at = last_attempt + MIN_REQUEST_SPACING
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('trend.collection.pacing_blocked',%s)",
                (
                    Jsonb(
                        {
                            "collection_run_id": str(run_id),
                            "provider": PROVIDER,
                            "geo": geo,
                            "next_eligible_at": next_eligible_at.isoformat(),
                        }
                    ),
                ),
            )
            return {
                "run_id": str(run_id),
                "geo": geo,
                "status": "blocked",
                "item_count": 0,
                "failure_category": "global_minimum_spacing",
                "next_eligible_at": next_eligible_at,
            }
        quota_row = conn.execute(
            "SELECT count(*) AS n FROM trend_collection_attempts WHERE attempted_at>now()-interval '1 hour'"
        ).fetchone()
        if quota_row is None:
            raise EngineFailure("trend_quota_state_unavailable")
        prior = quota_row["n"]
        if prior >= 12:
            conn.execute(
                "INSERT INTO audit_events(event_type,payload) VALUES ('trend.collection.quota_blocked',%s)",
                (
                    Jsonb(
                        {
                            "collection_run_id": str(run_id),
                            "provider": PROVIDER,
                            "geo": geo,
                            "hourly_cap": 12,
                        }
                    ),
                ),
            )
            return {
                "run_id": str(run_id),
                "geo": geo,
                "status": "blocked",
                "item_count": 0,
                "failure_category": "durable_hourly_limit",
            }
        conn.execute(
            "INSERT INTO trend_collection_attempts(id,provider,geo) VALUES (%s,%s,%s)",
            (run_id, PROVIDER, geo),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('trend.collection.started',%s)",
            (Jsonb({"collection_run_id": str(run_id), "provider": PROVIDER, "geo": geo}),),
        )
    try:
        with (
            external_run(str(run_id)),
            external_client(
                PROVIDER,
                "trend_collection",
                timeout=15,
                headers={"Accept": "application/rss+xml, application/xml"},
            ) as client,
            client.stream("GET", ENDPOINT, params={"geo": geo}) as response,
        ):
            http_status = response.status_code
            if response.status_code == 429:
                return _save_failure(
                    run_id, geo, "blocked", "provider_quota_or_rate_limit", http_status=429
                )
            if response.status_code != 200:
                return _save_failure(
                    run_id,
                    geo,
                    "failed",
                    f"http_{response.status_code}",
                    http_status=response.status_code,
                )
            blocks: list[bytes] = []
            size = 0
            for block in response.iter_bytes(65536):
                size += len(block)
                if size > MAX_RESPONSE_BYTES or time.monotonic() - started > 20:
                    return _save_failure(
                        run_id,
                        geo,
                        "failed",
                        "trend_feed_response_limit",
                        http_status=http_status,
                    )
                blocks.append(block)
        raw = b"".join(blocks)
        parsed = parse_feed(raw, geo)
    except FreeQuotaExceeded:
        return _save_failure(run_id, geo, "blocked", "provider_quota_or_rate_limit")
    except ExternalCallBlocked:
        return _save_failure(run_id, geo, "blocked", "external_policy_blocked")
    except (httpx.HTTPError, OSError):
        return _save_failure(run_id, geo, "failed", "trend_feed_network_error", http_status)
    except ValueError as exc:
        return _save_failure(run_id, geo, "failed", str(exc), http_status)

    with connection() as conn:
        conn.execute(
            """INSERT INTO trend_collection_runs
            (id,provider,geo,status,source_updated_at,response_sha256,item_count,http_status)
            VALUES (%s,%s,%s,'succeeded',%s,%s,%s,200)""",
            (
                run_id,
                PROVIDER,
                geo,
                parsed["source_updated_at"],
                parsed["response_sha256"],
                len(parsed["items"]),
            ),
        )
        volume_columns = {
            column["column_name"]
            for column in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='trend_observations'"
            ).fetchall()
        }
        for row in parsed["items"]:
            if {"source_volume_lower_bound", "source_volume_period"} <= volume_columns:
                conn.execute(
                    """INSERT INTO trend_observations
                    (run_id,geo,platform,query,source_rank,source_volume_label,source_volume_lower_bound,
                     source_volume_period,trend_started_at,source_updated_at,collected_at,related_terms,source_url,response_sha256,
                     raw_payload,source_categories,source_language)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,query) DO NOTHING""",
                    (run_id,row["geo"],row["platform"],row["query"],row["source_rank"],
                     row["source_volume_label"],row["source_volume_lower_bound"],row["source_volume_period"],
                     row["trend_started_at"],row["source_updated_at"],row["collected_at"],
                     row["related_terms"],row["source_url"],parsed["response_sha256"],
                     Jsonb(row['raw_payload']),row['source_categories'],row['source_language']),
                )
            else:
                conn.execute(
                    """INSERT INTO trend_observations
                    (run_id,geo,platform,query,source_rank,source_volume_label,trend_started_at,
                     source_updated_at,collected_at,related_terms,source_url,response_sha256)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,query) DO NOTHING""",
                    (run_id,row["geo"],row["platform"],row["query"],row["source_rank"],
                     row["source_volume_label"],row["trend_started_at"],row["source_updated_at"],
                     row["collected_at"],row["related_terms"],row["source_url"],parsed["response_sha256"]),
                )
        conn.execute(
            "INSERT INTO audit_events(event_type,payload) VALUES ('trend.collection.completed',%s)",
            (
                Jsonb(
                    {
                        "collection_run_id": str(run_id),
                        "provider": PROVIDER,
                        "geo": geo,
                        "item_count": len(parsed["items"]),
                        "http_status": 200,
                        "response_sha256": parsed["response_sha256"],
                        "source_rank_available": False,
                        "source_updated_at": parsed["source_updated_at"].isoformat()
                        if parsed["source_updated_at"]
                        else None,
                    }
                ),
            ),
        )
    return {
        "run_id": str(run_id),
        "geo": geo,
        "status": "succeeded",
        "http_status": 200,
        "item_count": len(parsed["items"]),
        "source_updated_at": parsed["source_updated_at"],
        "response_sha256": parsed["response_sha256"],
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "rank_available": False,
    }


def state() -> dict[str, Any]:
    with connection() as conn:
        schema_row = conn.execute(
            "SELECT to_regclass('public.trend_collection_runs') AS table_name"
        ).fetchone()
        exists = bool(schema_row and schema_row["table_name"])
        runs = (
            conn.execute(
                "SELECT * FROM trend_collection_runs ORDER BY started_at DESC LIMIT 100"
            ).fetchall()
            if exists
            else []
        )
        observations = observation_summaries(conn) if exists else []
    return {
        "provider": PROVIDER,
        "source_url": ENDPOINT,
        "terms_url": GOOGLE_TRENDS_HELP,
        "allowed_geos": sorted(ALLOWED_GEOS),
        "runs": runs,
        "observations": observations,
        "configured": bool(exists),
        "source_rank_semantics": "null unless the source explicitly supplies a rank",
        "source_volume_semantics": "bucketed Google estimate; lower bound is not an exact search count; period is unknown unless explicitly reported",
        "hours_parameter_status": "not_documented_and_not_used_for_collection",
    }


def observation_summaries(conn: Any, limit: int = 300) -> list[dict[str, Any]]:
    """Latest per-region query with observation lifecycle and cautious traffic comparison."""
    columns = {
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='trend_observations'"
        ).fetchall()
    }
    lower_expr = "source_volume_lower_bound" if "source_volume_lower_bound" in columns else "NULL::bigint"
    period_expr = "source_volume_period" if "source_volume_period" in columns else "NULL::text"
    topic_relations = conn.execute(
        """SELECT to_regclass('public.trend_topic_memberships') AS memberships,
        to_regclass('public.trend_topics') AS topics,
        to_regclass('public.trend_research_packages') AS packages"""
    ).fetchone()
    topics_exist = bool(topic_relations and all(topic_relations.values()))
    package_expr = (
        "COALESCE(p.status,'not_researched')" if topics_exist else "'not_researched'::text"
    )
    join_sql = """LEFT JOIN LATERAL (
        SELECT t.id FROM trend_topic_memberships m JOIN trend_topics t ON t.id=m.topic_id
        WHERE m.observation_id=o.id ORDER BY m.created_at DESC LIMIT 1
    ) t ON true
    LEFT JOIN LATERAL (
        SELECT status FROM trend_research_packages WHERE topic_id=t.id
        ORDER BY package_version DESC LIMIT 1
    ) p ON true""" if topics_exist else ""
    rows = conn.execute(
        f"""WITH history AS (
          SELECT o.*, lower(regexp_replace(btrim(o.query), '\\s+', ' ', 'g')) AS query_key,
            min(o.collected_at) OVER w AS first_observed,
            max(o.collected_at) OVER w AS last_observed,
            count(*) OVER w AS observation_count,
            lag(o.collected_at) OVER w AS previous_observed_at,
            lag({lower_expr}) OVER w AS previous_volume_lower_bound,
            lag({period_expr}) OVER w AS previous_volume_period,
            lag(o.source_url) OVER w AS previous_source_url,
            {lower_expr} AS volume_lower_bound,
            {period_expr} AS volume_period
          FROM trend_observations o
          WINDOW w AS (PARTITION BY o.geo,lower(regexp_replace(btrim(o.query), '\\s+', ' ', 'g'))
            ORDER BY o.collected_at,o.id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        ), latest AS (
          SELECT DISTINCT ON (geo,query_key) * FROM history
          ORDER BY geo,query_key,collected_at DESC,id DESC
        )
        SELECT o.id,o.run_id,o.geo,o.platform,o.query,o.source_rank,o.source_volume_label,
          o.volume_lower_bound AS source_volume_lower_bound,
          o.volume_period AS source_volume_period,o.trend_started_at,o.source_updated_at,
          o.collected_at,o.source_url,o.response_sha256,o.source_language,
          o.first_observed,o.last_observed,o.observation_count,o.previous_observed_at,
          CASE WHEN o.observation_count=1 THEN 'new'
            WHEN o.previous_observed_at IS NOT NULL AND o.collected_at-o.previous_observed_at>=interval '24 hours' THEN 'reappeared'
            ELSE 'continuing' END AS observation_status,
          CASE WHEN o.previous_observed_at IS NULL THEN 'no_prior_observation'
            WHEN o.volume_period IS NULL OR o.previous_volume_period IS NULL THEN 'period_unknown'
            WHEN o.volume_period<>o.previous_volume_period THEN 'period_changed'
            WHEN o.source_url<>o.previous_source_url THEN 'source_changed'
            WHEN o.volume_lower_bound IS NULL OR o.previous_volume_lower_bound IS NULL THEN 'bucket_unparsed'
            WHEN o.volume_lower_bound>o.previous_volume_lower_bound THEN 'bucket_up'
            WHEN o.volume_lower_bound<o.previous_volume_lower_bound THEN 'bucket_down'
            ELSE 'bucket_unchanged' END AS traffic_change_status,
          {package_expr} AS research_status
        FROM latest o {join_sql}
        ORDER BY o.collected_at DESC,o.id LIMIT %s""",
        (limit,),
    ).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        if row["source_volume_lower_bound"] is None:
            row["source_volume_lower_bound"] = parse_approx_traffic(row["source_volume_label"])
        row["source_volume_value_kind"] = "bucket_lower_bound" if row["source_volume_lower_bound"] is not None else "unavailable"
    return result


def choose_due_geo(
    attempts_by_geo: dict[str, datetime | None],
    last_global_attempt: datetime | None,
    now: datetime,
) -> str | None:
    """Choose the least-recently-attempted due region under the durable cap."""
    if now.tzinfo is None:
        raise ValueError("scheduler_time_must_be_timezone_aware")
    if last_global_attempt and now - last_global_attempt < MIN_REQUEST_SPACING:
        return None
    due: list[tuple[datetime | None, str]] = []
    for geo in sorted(ALLOWED_GEOS):
        last_attempt = attempts_by_geo.get(geo)
        if last_attempt is None or now - last_attempt >= COLLECTION_INTERVAL:
            due.append((last_attempt, geo))
    if not due:
        return None
    return min(due, key=lambda item: (item[0] or datetime.min.replace(tzinfo=UTC), item[1]))[1]


def choose_hourly_geo(
    attempts_by_geo: dict[str, datetime | None],
    attempted_this_hour: dict[str, list[dict[str, Any]]],
    last_global_attempt: datetime | None,
    now: datetime,
    *, allow_late: bool = False,
) -> tuple[str | None, str]:
    """Select one region for the current KST sweep without replaying completed slots."""
    if now.tzinfo is None:
        raise ValueError("scheduler_time_must_be_timezone_aware")
    current = now.astimezone(UTC)
    local = current.astimezone(SCHEDULE_TIMEZONE)
    bucket_local = local.replace(minute=0, second=0, microsecond=0)
    if not allow_late and not attempted_this_hour and local - bucket_local >= SCHEDULE_START_WINDOW:
        return None, "waiting_for_top_of_hour"
    if last_global_attempt and current - last_global_attempt < MIN_REQUEST_SPACING:
        return None, "not_due"
    retryable: list[tuple[datetime, str]] = []
    retry_pending = False
    for geo, rows in attempted_this_hour.items():
        if not rows or len(rows) >= MAX_ATTEMPTS_PER_GEO_HOUR:
            continue
        last = rows[-1]
        at = last.get("attempted_at")
        if (last.get("status") == "failed"
                and last.get("failure_category") in RETRYABLE_FAILURES
                and at is not None):
            if current - at >= MIN_REQUEST_SPACING:
                retryable.append((at, geo))
            else:
                retry_pending = True
    if retryable:
        return min(retryable)[1], "selected_retry"
    not_attempted = {
        geo: current if geo in attempted_this_hour else attempts_by_geo.get(geo)
        for geo in ALLOWED_GEOS
    }
    selected = choose_due_geo(not_attempted, None, current)
    if selected:
        return selected, "selected"
    if retry_pending:
        return None, "waiting_for_region_interval"
    if len(attempted_this_hour) >= len(ALLOWED_GEOS):
        return None, "hour_sweep_complete"
    return None, "waiting_for_region_interval"


def schedule_tick(now: datetime | None = None) -> dict[str, Any]:
    """Collect one due region in a persisted KST hourly sweep, at 5-minute spacing."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("scheduler_time_must_be_timezone_aware")
    current = current.astimezone(UTC)
    local = current.astimezone(SCHEDULE_TIMEZONE)
    bucket_local = local.replace(minute=0, second=0, microsecond=0)
    bucket = bucket_local.astimezone(UTC)
    with connection() as guard:
        locked = guard.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired",
            (SCHEDULER_LOCK,),
        ).fetchone()
        if not locked or not locked["acquired"]:
            return {"status": "busy", "geo": None, "external_calls": 0}
        try:
            hour_rows = guard.execute(
                """SELECT a.geo,a.attempted_at,r.status,r.failure_category
                FROM trend_collection_attempts a LEFT JOIN trend_collection_runs r ON r.id=a.id
                WHERE a.attempted_at >= %s ORDER BY a.attempted_at,a.geo""",
                (bucket,),
            ).fetchall()
            rolling = guard.execute(
                """SELECT count(*) AS n,min(attempted_at) AS oldest
                FROM trend_collection_attempts WHERE attempted_at>%s-interval '1 hour'""",
                (current,),
            ).fetchone()
            if rolling and rolling["n"] >= 12:
                return {"status": "rolling_hour_limit_wait", "geo": None,
                        "external_calls": 0, "hour_bucket": bucket.isoformat(),
                        "next_run_at": (rolling["oldest"] + timedelta(hours=1)).isoformat()}
            late_start=not hour_rows and local - bucket_local >= SCHEDULE_START_WINDOW
            per_geo = {
                str(row["geo"]): row["last_attempt"]
                for row in guard.execute(
                    """SELECT geo,max(attempted_at) AS last_attempt
                    FROM trend_collection_attempts GROUP BY geo"""
                ).fetchall()
            }
            latest = guard.execute(
                "SELECT max(attempted_at) AS last_attempt FROM trend_collection_attempts"
            ).fetchone()
            attempts_this_hour: dict[str, list[dict[str, Any]]] = {}
            for row in hour_rows:
                attempts_this_hour.setdefault(str(row["geo"]), []).append(dict(row))
            # A provider quota or policy stop pauses the entire sweep. Only a
            # transient network/5xx failure may consume the single spare call.
            hard_stop = next((row for row in reversed(hour_rows)
                              if row["status"] == "blocked" and row["failure_category"] in {
                                  "provider_quota_or_rate_limit", "external_policy_blocked"
                              }), None)
            if hard_stop:
                return {"status": "sweep_paused", "geo": None, "external_calls": 0,
                        "failure_category": hard_stop["failure_category"],
                        "hour_bucket": bucket.isoformat()}
            last_global = latest["last_attempt"] if latest else None
            due_geo, decision = choose_hourly_geo(per_geo, attempts_this_hour, last_global, current,
                                                 allow_late=late_start)
            if due_geo is None:
                next_run = (last_global + MIN_REQUEST_SPACING).isoformat() if decision == "not_due" and last_global else None
                next_hour = (bucket_local + timedelta(hours=1)).isoformat()
                if decision == "waiting_for_region_interval":
                    eligible_times = [
                        attempted_at + COLLECTION_INTERVAL
                        for geo, attempted_at in per_geo.items()
                        if geo not in attempts_this_hour and attempted_at is not None
                    ]
                    eligible_times.extend(
                        row["attempted_at"] + MIN_REQUEST_SPACING
                        for rows in attempts_this_hour.values()
                        for row in rows
                        if row["status"] == "failed"
                        and row["failure_category"] in RETRYABLE_FAILURES
                    )
                    if last_global:
                        eligible_times.append(last_global + MIN_REQUEST_SPACING)
                    next_run = min(eligible_times).isoformat() if eligible_times else next_hour
                status = (
                    "waiting_for_top_of_hour" if decision == "waiting_for_top_of_hour"
                    else "not_due" if decision in {"not_due", "waiting_for_region_interval"}
                    else "hour_sweep_complete"
                )
                return {"status": status, "geo": None, "external_calls": 0,
                        "hour_bucket": bucket.isoformat(), "next_run_at": next_run or next_hour}
            result = collect_geo(due_geo)
            return {**result, "scheduled": True, "hour_bucket": bucket.isoformat(),
                    "schedule_decision": 'current_hour_catch_up' if late_start else decision,
                    "external_calls": int(result.get("http_status") == 200)}
        finally:
            guard.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                (SCHEDULER_LOCK,),
            )
