"""Unit tests for pkb.dates: parse_date and relative_time."""

from datetime import date, datetime

import pytest

from pkb.dates import ParsedDate, parse_date, relative_time


# ── parse_date ─────────────────────────────────────────────────────────


def test_parse_date_none():
    assert parse_date(None) is None


def test_parse_date_empty_string():
    assert parse_date("") is None
    assert parse_date("   ") is None


def test_parse_date_year_str():
    pd = parse_date("2022")
    assert pd == ParsedDate(raw="2022", start="2022-01-01",
                            end="2023-01-01", precision="year")


def test_parse_date_year_int():
    pd = parse_date(2022)
    assert pd == ParsedDate(raw="2022", start="2022-01-01",
                            end="2023-01-01", precision="year")


def test_parse_date_month():
    pd = parse_date("2022-10")
    assert pd == ParsedDate(raw="2022-10", start="2022-10-01",
                            end="2022-11-01", precision="month")


def test_parse_date_december_rollover():
    pd = parse_date("2022-12")
    assert pd == ParsedDate(raw="2022-12", start="2022-12-01",
                            end="2023-01-01", precision="month")


def test_parse_date_day():
    pd = parse_date("2022-08-15")
    assert pd == ParsedDate(raw="2022-08-15", start="2022-08-15",
                            end="2022-08-16", precision="day")


def test_parse_date_datetime_obj():
    pd = parse_date(datetime(2024, 3, 15, 10, 30))
    assert pd == ParsedDate(raw="2024-03-15", start="2024-03-15",
                            end="2024-03-16", precision="day")


def test_parse_date_date_obj():
    pd = parse_date(date(2022, 8, 15))
    assert pd == ParsedDate(raw="2022-08-15", start="2022-08-15",
                            end="2022-08-16", precision="day")


def test_parse_date_datetime_string_with_T():
    pd = parse_date("2024-03-15T10:30:00Z")
    assert pd is not None
    assert pd.start == "2024-03-15"
    assert pd.end == "2024-03-16"
    assert pd.precision == "day"


def test_parse_date_datetime_string_with_space():
    pd = parse_date("2024-03-15 10:30:00")
    assert pd is not None
    assert pd.start == "2024-03-15"
    assert pd.precision == "day"


def test_parse_date_calendar_invalid():
    assert parse_date("2022-13-45") is None
    assert parse_date("2022-02-30") is None  # Feb doesn't have 30 days


def test_parse_date_format_invalid():
    assert parse_date("August 2022") is None
    assert parse_date("2022/10/15") is None
    assert parse_date("garbage") is None


def test_parse_date_int_out_of_range():
    assert parse_date(99) is None
    assert parse_date(12345) is None


def test_parse_date_bool_rejected():
    # bool is a subclass of int; make sure it doesn't slip through
    assert parse_date(True) is None
    assert parse_date(False) is None


def test_parse_date_other_types():
    assert parse_date([1, 2]) is None
    assert parse_date({"year": 2022}) is None


# ── relative_time ───────────────────────────────────────────────────────


def test_relative_time_year_precision():
    # Year precision always renders as bare year, regardless of distance
    assert relative_time("2022-01-01", "year",
                         today=date(2026, 5, 13)) == "2022"
    assert relative_time("2026-01-01", "year",
                         today=date(2026, 5, 13)) == "2026"


def test_relative_time_month_precision():
    assert relative_time("2024-10-01", "month",
                         today=date(2026, 5, 13)) == "Oct 2024"
    assert relative_time("2026-05-01", "month",
                         today=date(2026, 5, 13)) == "May 2026"


def test_relative_time_today():
    assert relative_time("2026-05-13", "day",
                         today=date(2026, 5, 13)) == "today"


def test_relative_time_yesterday():
    assert relative_time("2026-05-12", "day",
                         today=date(2026, 5, 13)) == "yesterday"


def test_relative_time_days_ago():
    assert relative_time("2026-05-08", "day",
                         today=date(2026, 5, 13)) == "5 days ago"
    assert relative_time("2026-05-01", "day",
                         today=date(2026, 5, 13)) == "12 days ago"


def test_relative_time_weeks_ago():
    assert relative_time("2026-04-20", "day",
                         today=date(2026, 5, 13)) == "3 weeks ago"


def test_relative_time_months_ago():
    # 60–364 days → "Mon YYYY"
    assert relative_time("2025-10-15", "day",
                         today=date(2026, 5, 13)) == "Oct 2025"


def test_relative_time_year_only_for_old():
    # ≥ 365 days → year only
    assert relative_time("2018-03-01", "day",
                         today=date(2026, 5, 13)) == "2018"


def test_relative_time_future_near():
    # Future, |delta| < 365 → "Mon YYYY"
    assert relative_time("2026-05-14", "day",
                         today=date(2026, 5, 13)) == "May 2026"
    assert relative_time("2026-08-01", "day",
                         today=date(2026, 5, 13)) == "Aug 2026"


def test_relative_time_future_far():
    # Future, |delta| ≥ 365 → year only
    assert relative_time("2030-01-01", "day",
                         today=date(2026, 5, 13)) == "2030"


def test_relative_time_none_input():
    assert relative_time(None, "year") is None
    assert relative_time("", "year") is None


def test_relative_time_invalid_input():
    assert relative_time("not-a-date", "day") is None
    assert relative_time("2022", "day") is None  # not full ISO


def test_relative_time_day_precision_default_today():
    # No `today` arg — uses date.today(); just verify it returns a string
    today_iso = date.today().isoformat()
    assert relative_time(today_iso, "day") == "today"
