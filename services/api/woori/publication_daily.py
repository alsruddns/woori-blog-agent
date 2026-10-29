"""KST daily publication accounting for the read-only operations dashboard."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
GLOBAL_DAILY_PUBLISH_LIMIT = 50
LANGUAGE_DAILY_LIMITS = {"ko": 10, "ja": 10, "zh-CN": 5}
LANGUAGE_HOURLY_LIMITS = {"en": 20, "ko": 10, "ja": 10, "zh-CN": 10}


def kst_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return UTC bounds for a KST calendar date (end exclusive)."""
    start = datetime.combine(day, time.min, KST)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def summarize_daily_usage(
    published_by_language: dict[str, int], reserved_by_language: dict[str, int]
) -> dict[str, object]:
    """Reservations consume headroom conservatively; English uses global remainder."""
    published = {key: max(0, int(value)) for key, value in published_by_language.items()}
    reserved = {key: max(0, int(value)) for key, value in reserved_by_language.items()}
    published_total = sum(published.values())
    reserved_total = sum(reserved.values())
    global_remaining = max(0, GLOBAL_DAILY_PUBLISH_LIMIT - published_total - reserved_total)
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
        "global_limit": GLOBAL_DAILY_PUBLISH_LIMIT,
        "published": published_total,
        "reserved": reserved_total,
        "remaining": global_remaining,
        "languages": languages,
        "auto_enabled": False,
        "remote_manual_sync": "not_verified",
        "remote_count_is_authoritative": False,
    }
