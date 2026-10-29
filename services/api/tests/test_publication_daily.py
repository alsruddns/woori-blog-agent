from datetime import date, datetime, UTC

from woori.publication_daily import kst_day_bounds, summarize_daily_usage


def test_kst_calendar_day_bounds_are_utc_and_half_open() -> None:
    start, end = kst_day_bounds(date(2026, 10, 29))
    assert start == datetime(2026, 10, 28, 15, tzinfo=UTC)
    assert end == datetime(2026, 10, 29, 15, tzinfo=UTC)


def test_language_limits_and_english_uses_dynamic_global_remainder() -> None:
    usage = summarize_daily_usage(
        {"ko": 10, "ja": 10, "zh-CN": 5, "en": 8},
        {"ko": 0, "ja": 0, "zh-CN": 0, "en": 2},
    )
    assert usage["published"] == 33
    assert usage["reserved"] == 2
    assert usage["remaining"] == 15
    assert usage["languages"]["ko"]["remaining"] == 0
    assert usage["languages"]["en"]["remaining"] == 15
    assert usage["languages"]["en"]["hourly_limit"] == 20
    assert usage["auto_enabled"] is False


def test_english_limit_is_not_a_fixed_quota() -> None:
    usage = summarize_daily_usage({"en": 0, "ko": 0, "ja": 0, "zh-CN": 0}, {})
    assert usage["languages"]["en"]["limit"] == 50
