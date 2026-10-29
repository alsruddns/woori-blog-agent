"""Bounded, allowlisted Google Trends RSS collection; feed sequence is not a rank."""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import uuid4

import httpx
from psycopg.types.json import Jsonb

from .ai import EngineFailure
from .db import connection
from .external_policy import ExternalCallBlocked, FreeQuotaExceeded
from .external_policy import client as external_client

PROVIDER = "google_trends_rss"
ENDPOINT = "https://trends.google.com/trending/rss"
ALLOWED_GEOS = {"KR", "US", "JP", "TW", "HK", "SG", "GB", "CA", "AU", "IN", "PH"}
GOOGLE_TRENDS_HELP = "https://support.google.com/trends/answer/3076011?hl=en"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ITEMS = 20
COLLECTION_INTERVAL = timedelta(hours=1)
MIN_REQUEST_SPACING = timedelta(minutes=5)
SCHEDULER_LOCK = "google_trends_hourly_scheduler"
NS = {"ht": "https://trends.google.com/trending/rss"}


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
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
                "source_rank": None,
                "source_volume_label": traffic.strip()[:80] if traffic else None,
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
        for row in parsed["items"]:
            conn.execute(
                """INSERT INTO trend_observations
                (run_id,geo,platform,query,source_rank,source_volume_label,trend_started_at,
                 source_updated_at,collected_at,related_terms,source_url,response_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(run_id,query) DO NOTHING""",
                (
                    run_id,
                    row["geo"],
                    row["platform"],
                    row["query"],
                    row["source_rank"],
                    row["source_volume_label"],
                    row["trend_started_at"],
                    row["source_updated_at"],
                    row["collected_at"],
                    row["related_terms"],
                    row["source_url"],
                    parsed["response_sha256"],
                ),
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
        observations = (
            conn.execute(
                "SELECT * FROM trend_observations ORDER BY collected_at DESC,id LIMIT 300"
            ).fetchall()
            if exists
            else []
        )
    return {
        "provider": PROVIDER,
        "source_url": ENDPOINT,
        "terms_url": GOOGLE_TRENDS_HELP,
        "allowed_geos": sorted(ALLOWED_GEOS),
        "runs": runs,
        "observations": observations,
        "configured": bool(exists),
        "source_rank_semantics": "null unless the source explicitly supplies a rank",
    }


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


def schedule_tick(now: datetime | None = None) -> dict[str, Any]:
    """Collect at most one due region; safe for multiple local worker processes."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("scheduler_time_must_be_timezone_aware")
    with connection() as guard:
        locked = guard.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired",
            (SCHEDULER_LOCK,),
        ).fetchone()
        if not locked or not locked["acquired"]:
            return {"status": "busy", "geo": None, "external_calls": 0}
        try:
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
            due_geo = choose_due_geo(
                per_geo,
                latest["last_attempt"] if latest else None,
                current,
            )
            if due_geo is None:
                return {"status": "not_due", "geo": None, "external_calls": 0}
            result = collect_geo(due_geo)
            return {**result, "scheduled": True, "external_calls": int(result.get("http_status") == 200)}
        finally:
            guard.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                (SCHEDULER_LOCK,),
            )
