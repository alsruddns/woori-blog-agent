"""KST daily publication accounting for the read-only operations dashboard."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
GLOBAL_DAILY_PUBLISH_LIMIT = 100
LANGUAGE_DAILY_LIMITS = {"ko": 10, "ja": 10, "zh-CN": 5}
LANGUAGE_HOURLY_LIMITS = {"en": 20, "ko": 10, "ja": 10, "zh-CN": 10}


def kst_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return UTC bounds for a KST calendar date (end exclusive)."""
    start = datetime.combine(day, time.min, KST)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def verified_live_by_language(conn: Any, start: datetime, end: datetime) -> dict[str, int]:
    """Count distinct observed LIVE posts; drafts and duplicate ledger/record rows do not count."""
    rows = conn.execute(
        """WITH live_posts AS (
          SELECT b.language_code,b.blog_id AS remote_blog_id,r.remote_post_id
          FROM publishing_records r JOIN blogger_blogs b ON b.id=r.blog_id
          WHERE b.active AND r.remote_status='LIVE' AND r.remote_verified_at IS NOT NULL
            AND r.remote_post_id IS NOT NULL AND r.published_at>=%s AND r.published_at<%s
          UNION
          SELECT b.language_code,b.blog_id AS remote_blog_id,a.payload->>'post_id' AS remote_post_id
          FROM audit_events a JOIN blogger_blogs b ON b.blog_id=a.payload->>'blog_id'
          WHERE b.active AND a.event_type='blogger.write.succeeded' AND a.payload->>'mode'='live'
            AND a.payload->>'operation' IN ('create_live','publish_draft')
            AND a.payload->>'post_id' IS NOT NULL AND a.created_at>=%s AND a.created_at<%s
            AND NOT EXISTS (SELECT 1 FROM publishing_records r
              JOIN blogger_blogs rb ON rb.id=r.blog_id
              WHERE rb.blog_id=a.payload->>'blog_id' AND r.remote_post_id=a.payload->>'post_id'
                AND r.remote_status='LIVE' AND r.remote_verified_at IS NOT NULL)
        ) SELECT language_code,count(*)::int AS count FROM live_posts
          GROUP BY language_code""",
        (start, end, start, end),
    ).fetchall()
    return {str(row["language_code"]): int(row["count"]) for row in rows}


def summarize_daily_usage(
    published_by_language: dict[str, int], reserved_by_language: dict[str, int],
    global_daily_limit: int = GLOBAL_DAILY_PUBLISH_LIMIT,
) -> dict[str, object]:
    """Reservations consume headroom conservatively; English uses global remainder."""
    published = {key: max(0, int(value)) for key, value in published_by_language.items()}
    reserved = {key: max(0, int(value)) for key, value in reserved_by_language.items()}
    published_total = sum(published.values())
    reserved_total = sum(reserved.values())
    global_daily_limit = max(1, int(global_daily_limit))
    global_remaining = max(0, global_daily_limit - published_total - reserved_total)
    languages = {}
    for language in ("en", "ko", "ja", "zh-CN"):
        used = published.get(language, 0)
        held = reserved.get(language, 0)
        remaining = global_remaining if language == "en" else max(
            0, LANGUAGE_DAILY_LIMITS[language] - used - held
        )
        languages[language] = {
            "published": used,
            "reserved": held,
            "limit": (used + held + remaining) if language == "en" else LANGUAGE_DAILY_LIMITS[language],
            "remaining": remaining,
            "hourly_limit": LANGUAGE_HOURLY_LIMITS[language],
        }
    return {
        "timezone": "Asia/Seoul",
        "global_limit": global_daily_limit,
        "published": published_total,
        "reserved": reserved_total,
        "remaining": global_remaining,
        "languages": languages,
        "auto_enabled": False,
        "remote_manual_sync": "not_verified",
        "remote_count_is_authoritative": False,
    }
