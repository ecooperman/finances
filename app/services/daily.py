"""Daily-spread budget items: a monthly amount treated as a per-day
allowance, with the day's real costs logged against it.

A day's *effective* amount is the sum of its logged entries if there are any,
else the planned allowance (so unlogged days assume you spent as planned and
the numbers fall back to the budget if you stop logging).
"""

from calendar import monthrange
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .. import models
from .schedule import active_in_month, daily_amounts


def month_spend(db: Session, year: int, mon: int) -> Dict[int, Dict[int, List[models.DailySpend]]]:
    """item_id -> day -> [entries] for the month."""
    n = monthrange(year, mon)[1]
    rows = (
        db.query(models.DailySpend)
        .filter(models.DailySpend.date >= date(year, mon, 1), models.DailySpend.date <= date(year, mon, n))
        .order_by(models.DailySpend.id)
        .all()
    )
    out: Dict[int, Dict[int, List[models.DailySpend]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[r.recurring_item_id][r.date.day].append(r)
    return out


def build_days(monthly_cents: int, year: int, mon: int, by_day: Optional[dict]) -> List[dict]:
    """The per-day breakdown (DailyDay dicts) for one item in a month."""
    by_day = by_day or {}
    allowances = daily_amounts(monthly_cents, monthrange(year, mon)[1])
    days = []
    for i, allowance in enumerate(allowances, start=1):
        entries = by_day.get(i, [])
        days.append({
            "day": i,
            "allowance_cents": allowance,
            "spent_cents": sum(e.amount_cents for e in entries),
            "entries": [{"id": e.id, "amount_cents": e.amount_cents, "note": e.note} for e in entries],
        })
    return days


def effective(day: dict) -> int:
    return day["spent_cents"] if day["entries"] else day["allowance_cents"]


def month_total(days: List[dict]) -> int:
    return sum(effective(d) for d in days)


def daily_budget(db: Session, on: date, person_id: Optional[int] = None) -> List[dict]:
    """Standing of each active daily-spread item as of `on`."""
    month = on.strftime("%Y-%m")
    spend = month_spend(db, on.year, on.month)
    items = (
        db.query(models.RecurringItem)
        .filter(models.RecurringItem.spread_daily.is_(True))
        .order_by(models.RecurringItem.name)
        .all()
    )
    n = monthrange(on.year, on.month)[1]
    out = []
    for item in items:
        if not active_in_month(item, month):
            continue
        if person_id is not None and item.person_id != person_id:
            continue
        days = build_days(item.amount_cents, on.year, on.month, spend.get(item.id))
        today = days[on.day - 1]
        through = days[: on.day]
        days_left = n - on.day
        month_left = item.amount_cents - sum(effective(d) for d in through)
        out.append({
            "item_id": item.id,
            "name": item.name,
            "category": item.category,
            "person": item.person,
            "monthly_cents": item.amount_cents,
            "allowance_cents": today["allowance_cents"],
            "spent_today_cents": today["spent_cents"],
            "left_today_cents": today["allowance_cents"] - today["spent_cents"],
            "entries_today": today["entries"],
            "logged_over_under_cents": sum(
                d["spent_cents"] - d["allowance_cents"] for d in through if d["entries"]
            ),
            "month_left_cents": month_left,
            "days_left": days_left,
            "per_day_left_cents": (month_left // days_left) if days_left > 0 else None,
        })
    return out
