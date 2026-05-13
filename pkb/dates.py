"""Precision-aware date parsing and rendering.

Supports partial-precision dates (year, year-month, year-month-day) so a
`published_at: 2018` round-trips faithfully through the system without being
silently padded to "Jan 2018" in display, while still being filter-comparable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


@dataclass(frozen=True)
class ParsedDate:
    """Parsed date with explicit precision and half-open interval [start, end)."""

    raw: str          # original string form for display
    start: str        # YYYY-MM-DD, inclusive
    end: str          # YYYY-MM-DD, exclusive
    precision: str    # 'year' | 'month' | 'day'


def parse_date(value: object | None) -> ParsedDate | None:
    """Parse a YAML-decoded value into a ParsedDate.

    Handles:
      - None → None
      - datetime.datetime → day precision
      - datetime.date → day precision
      - int (1000–9999) → year precision
      - str with optional T-/space-time suffix → matches YYYY, YYYY-MM, YYYY-MM-DD
      - anything else → None (logs a warning)

    Calendar validation: returns None for impossible dates like 2022-13-45.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return _from_date(value.date(), raw=value.date().isoformat())
    if isinstance(value, date):
        return _from_date(value, raw=value.isoformat())
    if isinstance(value, bool):
        # bool is a subclass of int — reject explicitly so True/False don't slip through
        logger.warning("invalid date %r — dropping", value)
        return None
    if isinstance(value, int):
        if 1000 <= value <= 9999:
            return _from_year(value, raw=str(value))
        logger.warning("invalid date int %r — dropping", value)
        return None
    if not isinstance(value, str):
        logger.warning("invalid date type %r — dropping", value)
        return None

    raw = value
    s = value.strip()
    if not s:
        return None

    # Truncate optional time suffix: "2024-03-15T10:30:00Z" → "2024-03-15"
    s = re.split(r"[T ]", s, maxsplit=1)[0]

    m = _DATE_RE.match(s)
    if not m:
        logger.warning("invalid date %r — dropping", value)
        return None

    y_str, mo_str, d_str = m.group(1), m.group(2), m.group(3)
    y = int(y_str)

    if d_str is not None:
        try:
            mo, d = int(mo_str), int(d_str)
            start_date = date(y, mo, d)
        except ValueError:
            logger.warning("invalid date %r — dropping", value)
            return None
        end_date = start_date + timedelta(days=1)
        return ParsedDate(raw=raw, start=start_date.isoformat(),
                          end=end_date.isoformat(), precision="day")

    if mo_str is not None:
        try:
            mo = int(mo_str)
            start_date = date(y, mo, 1)
        except ValueError:
            logger.warning("invalid date %r — dropping", value)
            return None
        if mo == 12:
            end_date = date(y + 1, 1, 1)
        else:
            end_date = date(y, mo + 1, 1)
        return ParsedDate(raw=raw, start=start_date.isoformat(),
                          end=end_date.isoformat(), precision="month")

    return _from_year(y, raw=raw)


def _from_date(d: date, raw: str) -> ParsedDate:
    return ParsedDate(raw=raw, start=d.isoformat(),
                      end=(d + timedelta(days=1)).isoformat(), precision="day")


def _from_year(y: int, raw: str) -> ParsedDate:
    return ParsedDate(raw=raw, start=f"{y:04d}-01-01",
                      end=f"{y + 1:04d}-01-01", precision="year")


def relative_time(start: str | None, precision: str | None,
                  today: date | None = None) -> str | None:
    """Render a normalized date as a human-friendly relative string.

    Precision-aware:
      - 'year'  → always 'YYYY'
      - 'month' → always 'Mon YYYY'
      - 'day' or None → distance-based:
          future, |delta| < 365 → 'Mon YYYY'
          future, |delta| ≥ 365 → 'YYYY'
          today / yesterday / N days ago / N weeks ago / Mon YYYY / YYYY

    Returns None for falsy or unparseable input.
    """
    if not start:
        return None
    try:
        d_start = date.fromisoformat(start)
    except (ValueError, TypeError):
        return None

    if precision == "year":
        return f"{d_start.year}"
    if precision == "month":
        return d_start.strftime("%b %Y")

    if today is None:
        today = date.today()
    delta = (today - d_start).days

    if delta < 0:
        if abs(delta) < 365:
            return d_start.strftime("%b %Y")
        return f"{d_start.year}"
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta < 14:
        return f"{delta} days ago"
    if delta < 60:
        return f"{delta // 7} weeks ago"
    if delta < 365:
        return d_start.strftime("%b %Y")
    return f"{d_start.year}"
