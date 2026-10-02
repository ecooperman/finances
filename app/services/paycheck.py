"""How much is left to pay before the next paycheck.

Walks the real dated payments (recurring items placed by `schedule.py`, plus
one-off transactions) forward from `on`, finds the next dated income, and
totals the money-out between now and then. Everything here uses each
payment's real face amount - none of the smoothing the monthly totals use.

Items that can't be placed on a date (monthly with no day_of_month, weekly
with no day_of_week) can't be counted; they're returned in `undated` so the
UI can say so instead of silently under-reporting.
"""

from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from .. import models
from .schedule import active_in_month, cadence_hits, occurrence_days, shift_month

HORIZON_DAYS = 62  # how far ahead to look for a paycheck


def _months_between(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _payment(on_date: date, name: str, amount_cents: int, kind: str, **extra) -> dict:
    return {"date": on_date, "name": name, "amount_cents": amount_cents, "kind": kind, **extra}


def dated_events(db: Session, start: date, end: date):
    """All dated money events in [start, end] inclusive.

    Returns (events, undated): `events` is a list of dicts
    {date, name, amount_cents, direction, kind, person_id}; `undated` is the
    recurring items that land in that span but have no day to place them on
    (deduplicated, one entry per item).
    """
    events: List[dict] = []
    undated = {}
    items = db.query(models.RecurringItem).all()
    items_by_id = {i.id: i for i in items}
    deferrals = db.query(models.PaymentDeferral).all()
    # payments marked "couldn't pay this month" are not due that month...
    deferred = {(d.recurring_item_id, d.month) for d in deferrals
                if d.origin_id is None and d.recurring_item_id is not None}
    deferred_txns = {d.transaction_id for d in deferrals
                     if d.origin_id is None and d.transaction_id is not None}
    txn_ids = [d.transaction_id for d in deferrals if d.transaction_id is not None]
    txns_by_id = (
        {t.id: t for t in db.query(models.Transaction).filter(models.Transaction.id.in_(txn_ids))}
        if txn_ids else {}
    )
    # ...they come back on the 1st of the next month, unless carried again.
    carried_again = {d.origin_id for d in deferrals if d.origin_id is not None}
    for d in deferrals:
        item = (txns_by_id.get(d.transaction_id) if d.transaction_id is not None
                else items_by_id.get(d.recurring_item_id))
        name = getattr(item, "description", None) or getattr(item, "name", None)
        y, m = (int(p) for p in shift_month(d.month, 1).split("-"))
        when = date(y, m, 1)
        if item is not None and d.id not in carried_again and start <= when <= end:
            events.append({
                **_payment(when, name, d.amount_cents, "carryover"),
                "direction": item.direction,
                "person_id": item.person_id,
            })

    for year, mon in _months_between(start, end):
        month = f"{year:04d}-{mon:02d}"
        for item in items:
            if not active_in_month(item, month):
                continue
            if not cadence_hits(item.frequency, item.anchor_month, mon):
                continue
            if (item.id, month) in deferred:
                continue
            days = occurrence_days(
                item.frequency, item.day_of_month, item.day_of_week, item.week_anchor, year, mon
            )
            if days is None:
                undated.setdefault(item.id, item)
                continue
            for d in days:
                when = date(year, mon, d)
                if start <= when <= end:
                    events.append({
                        **_payment(when, item.name, item.amount_cents, "recurring"),
                        "direction": item.direction,
                        "person_id": item.person_id,
                    })

    txns = (
        db.query(models.Transaction)
        .filter(models.Transaction.date >= start, models.Transaction.date <= end)
        .all()
    )
    for t in txns:
        if t.id in deferred_txns:
            continue
        events.append({
            **_payment(t.date, t.description, t.amount_cents, "transaction"),
            "direction": t.direction,
            "person_id": t.person_id,
        })

    events.sort(key=lambda e: (e["date"], e["name"].lower()))
    return events, list(undated.values())


def until_next_paycheck(
    db: Session, on: date, person_id: Optional[int] = None
) -> dict:
    """The lookahead from `on` (inclusive) to the next paycheck.

    "Paycheck" = any dated recurring income (optionally only `person_id`'s).
    One that lands on `on` itself counts as already received, so the next one
    is the first strictly after. Payments dated on the paycheck day are
    reported separately from those before it.
    """
    horizon_end = on + timedelta(days=HORIZON_DAYS)
    events, undated_items = dated_events(db, on, horizon_end)

    paychecks = [
        e for e in events
        if e["direction"] == "in"
        and e["kind"] == "recurring"
        and e["date"] > on
        and (person_id is None or e["person_id"] == person_id)
    ]
    nxt = paychecks[0] if paychecks else None  # events are date-sorted

    result = {
        "as_of": on,
        "next_paycheck": None,
        "before": [],
        "before_total_cents": 0,
        "on_payday": [],
        "on_payday_total_cents": 0,
        "undated": [],
    }
    if nxt is None:
        return result

    outs = [e for e in events if e["direction"] == "out"]
    before = [e for e in outs if on <= e["date"] < nxt["date"]]
    on_payday = [e for e in outs if e["date"] == nxt["date"]]

    result["next_paycheck"] = {
        "date": nxt["date"],
        "name": nxt["name"],
        "amount_cents": nxt["amount_cents"],
        "days_away": (nxt["date"] - on).days,
    }
    result["before"] = before
    result["before_total_cents"] = sum(e["amount_cents"] for e in before)
    result["on_payday"] = on_payday
    result["on_payday_total_cents"] = sum(e["amount_cents"] for e in on_payday)

    # Only money-out items matter for "left to pay", and only ones whose month
    # overlaps the span we actually counted.
    span_months = {(y, m) for y, m in _months_between(on, nxt["date"])}
    result["undated"] = [
        {"name": i.name, "amount_cents": i.amount_cents, "frequency": i.frequency}
        for i in undated_items
        if i.direction == "out"
        and any(
            active_in_month(i, f"{y:04d}-{m:02d}") and cadence_hits(i.frequency, i.anchor_month, m)
            for y, m in span_months
        )
    ]
    return result
