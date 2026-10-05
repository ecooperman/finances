"""Opening / closing balance for a month, rolled over automatically.

A month's *closing* balance = its opening balance + its dated net cash flow
(the same figure the calendar's running total ends on: dated items only, so
items with no set day aren't in it). The next month *opens* with that
closing balance, unless there's a manual override for it - which then
becomes the new starting point for everything after.

The chain starts at the rollover start month (an app setting, seeded by the
migration) or the earliest override, whichever is earlier. Months before it
open at $0 and don't roll. The balance is household-wide: it ignores any
person/category filter and any scenario.
"""

from datetime import date
from typing import Dict, Optional

from sqlalchemy.orm import Session

from .. import models
from .schedule import shift_month

START_KEY = "rollover_start_month"


def rollover_start(db: Session) -> str:
    """The configured start month, created (as the current month) if unset."""
    row = db.get(models.AppSetting, START_KEY)
    if row is None:
        row = models.AppSetting(key=START_KEY, value=date.today().strftime("%Y-%m"))
        db.add(row)
        db.commit()
    return row.value


def overrides(db: Session) -> Dict[str, models.MonthOpeningBalance]:
    return {o.month: o for o in db.query(models.MonthOpeningBalance).all()}


def _dated_items(db: Session, month: str) -> list:
    """Every dated money event of the month (base: no filters, no scenario),
    one dict per day it lands: {day, signed_cents, direction, logged_cents}.
    `logged_cents` is set for a daily-spread day with real costs logged
    (what's actually been spent). Items with no day are left out, matching
    the calendar's running total."""
    # imported here: monthly imports this module
    from .daily import effective
    from .monthly import _deferral_rows, _month_parts, _recurring_rows, _txn_rows, _UNCOUNTED

    _, mon, start, end = _month_parts(month)
    filters = (None, False, None)
    rows = _recurring_rows(db, month, mon, filters, normalized=False) + _txn_rows(db, start, end, filters)
    rows = _deferral_rows(db, month, filters, rows)
    items = []
    for r in rows:
        if r["effect"] in _UNCOUNTED:
            continue
        sign = 1 if r["direction"] == "in" else -1
        if r["daily"] is not None:
            for d in r["daily"]:
                items.append({"day": d["day"], "signed_cents": sign * effective(d),
                              "direction": r["direction"],
                              "logged_cents": d["spent_cents"] if d["entries"] else None})
        elif r["occurrence_days"]:
            for day in r["occurrence_days"]:
                items.append({"day": day, "signed_cents": sign * r["face_amount_cents"],
                              "direction": r["direction"], "logged_cents": None})
        elif r["day"] is not None:
            items.append({"day": r["day"], "signed_cents": sign * r["amount_cents"],
                          "direction": r["direction"], "logged_cents": None})
    return items


def dated_net_cents(db: Session, month: str) -> int:
    """Net cash flow of the month's *dated* items - what the calendar's
    running total adds up over the month."""
    return sum(i["signed_cents"] for i in _dated_items(db, month))


def balance_as_of(db: Session, on: date) -> int:
    """The balance at the start of `on`: the month's opening balance plus
    everything dated before today, plus today's income (a paycheck landing
    today counts as received) and minus the daily spending already logged
    today. Today's other payments are still ahead of you, so they're left
    out - the "until next paycheck" lookahead counts them."""
    month = on.strftime("%Y-%m")
    total = opening_balance(db, month)["opening_cents"]
    for i in _dated_items(db, month):
        if i["day"] < on.day:
            total += i["signed_cents"]
        elif i["day"] == on.day:
            if i["direction"] == "in":
                total += i["signed_cents"]
            elif i["logged_cents"] is not None:
                total -= i["logged_cents"]
    return total


def opening_balance(db: Session, month: str) -> dict:
    """The OpeningBalance for `month` (see schemas.OpeningBalance)."""
    over = overrides(db)
    origin = min([rollover_start(db), *over.keys()])
    # Before the chain starts there is nothing to roll: that month stands alone.
    first = month if month < origin else origin

    result = None
    closing_prev: Optional[int] = None
    m = first
    while True:
        o = over.get(m)
        computed = closing_prev if closing_prev is not None else 0
        opening = o.amount_cents if o is not None else computed
        closing = opening + dated_net_cents(db, m)
        if m == month:
            result = {
                "month": m,
                "computed_cents": computed,
                "override_cents": o.amount_cents if o is not None else None,
                "note": o.note if o is not None else None,
                "opening_cents": opening,
                "closing_cents": closing,
                "from_month": shift_month(m, -1) if closing_prev is not None else None,
            }
            break
        closing_prev = closing
        m = shift_month(m, 1)
    return result


def set_override(db: Session, month: str, amount_cents: int, note: Optional[str]):
    row = db.query(models.MonthOpeningBalance).filter_by(month=month).first()
    if row is None:
        row = models.MonthOpeningBalance(month=month, amount_cents=amount_cents, note=note)
        db.add(row)
    else:
        row.amount_cents = amount_cents
        row.note = note
    db.commit()
    return row


def clear_override(db: Session, month: str) -> bool:
    n = db.query(models.MonthOpeningBalance).filter_by(month=month).delete()
    db.commit()
    return n > 0
