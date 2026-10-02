"""Where a recurring item actually falls on the calendar.

Shared by the monthly view (`monthly.py`, which hands the Overview calendar
the real pay days) and the "until next paycheck" lookahead (`paycheck.py`).
The totals elsewhere in the app are deliberately smoothed; everything here
is about real dates and the real, per-payment (face) amount.
"""

from calendar import monthrange
from datetime import date
from typing import List, Optional

from .. import models
from ..models import FREQUENCY_INTERVAL_MONTHS


def cadence_hits(frequency: str, anchor_month: Optional[int], mon: int) -> bool:
    """Does a recurring item with this cadence land in calendar month `mon`?
    Weekly/biweekly/monthly land every month; the sub-monthly ones only in
    their anchor month(s)."""
    interval = FREQUENCY_INTERVAL_MONTHS.get(frequency)
    if interval is None:
        return True
    if anchor_month is None:  # sub-monthly item with no anchor - treat as not landing
        return False
    return (mon - anchor_month) % interval == 0


def active_in_month(item: models.RecurringItem, month: str) -> bool:
    """`month` is "YYYY-MM"; honours active + the optional start/end bounds."""
    if not item.active:
        return False
    if item.start_month and item.start_month > month:
        return False
    if item.end_month and item.end_month < month:
        return False
    return True


def occurrence_days(
    frequency: str,
    day_of_month: Optional[int],
    day_of_week: Optional[int],
    week_anchor: Optional[date],
    year: int,
    mon: int,
) -> Optional[List[int]]:
    """Days of the month (1-31) the item pays on, or None if it has no
    date to place it by (monthly with no day_of_month, weekly with no
    day_of_week).

    The caller is responsible for checking `cadence_hits` / `active_in_month`
    first - this only answers "which days, given it lands this month".
    """
    last = monthrange(year, mon)[1]
    if frequency in ("weekly", "biweekly"):
        if day_of_week is None:
            return None
        # stored 0=Sunday..6=Saturday; Python's weekday() is 0=Monday..6=Sunday
        py_dow = (day_of_week - 1) % 7
        days = [d for d in range(1, last + 1) if date(year, mon, d).weekday() == py_dow]
        if frequency == "biweekly":
            if week_anchor is not None:
                days = [d for d in days if (date(year, mon, d) - week_anchor).days % 14 == 0]
            else:
                # no anchor: every other matching weekday from the first one
                days = days[::2]
        return days
    if day_of_month is None:
        return None
    return [min(day_of_month, last)]  # day 31 in a 30-day month -> the 30th


def shift_month(month: str, delta: int) -> str:
    """"YYYY-MM" moved by `delta` months (negative = earlier)."""
    y, m = (int(p) for p in month.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"
