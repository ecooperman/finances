"""The monthly-view aggregation - the one piece of real logic in this app.

`compute_month` takes a calendar month plus optional person / category
filters and an optional saved scenario, and returns everything the Monthly
page renders: the money-in and money-out rows for that month, the true
cash-flow totals, a "normalized" (lumpy recurring items smoothed to a
per-month average) set of totals, and - when a scenario is supplied - the
same again with the scenario's add/remove/modify adjustments layered on
plus the delta between the two.

Scenarios never touch stored rows: the adjustments are applied to
in-memory copies here and thrown away when the request ends.
"""

from calendar import monthrange
from datetime import date
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from .. import models
from ..models import FREQUENCY_MONTHS
from ..schemas import (
    Category,
    MonthResult,
    MonthRow,
    MonthSide,
    MonthTotals,
    Person,
    ScenarioMonthResult,
)


def _month_parts(month: str):
    year, mon = (int(p) for p in month.split("-"))
    start = date(year, mon, 1)
    end = date(year, mon, monthrange(year, mon)[1])
    return year, mon, start, end


def _cadence_hits(frequency: str, anchor_month: Optional[int], mon: int) -> bool:
    """Does a recurring item with this cadence land in calendar month `mon`?"""
    interval = FREQUENCY_MONTHS.get(frequency, 1)
    if interval == 1:
        return True
    if anchor_month is None:  # non-monthly item with no anchor - treat as not landing
        return False
    return (mon - anchor_month) % interval == 0


def _active_in_month(item: models.RecurringItem, month: str) -> bool:
    if not item.active:
        return False
    if item.start_month and item.start_month > month:
        return False
    if item.end_month and item.end_month < month:
        return False
    return True


def _passes_filters(
    row_person_id: Optional[int],
    row_category_id: Optional[int],
    person_id: Optional[int],
    joint_only: bool,
    category_ids: Optional[Iterable[int]],
) -> bool:
    if joint_only:
        if row_person_id is not None:
            return False
    elif person_id is not None:
        if row_person_id != person_id:
            return False
    if category_ids:
        if row_category_id not in set(category_ids):
            return False
    return True


def _row(kind, id_, name, amount_cents, direction, *, frequency=None, day=None,
         category=None, person=None, effect="normal", original_amount_cents=None) -> dict:
    return dict(
        kind=kind, id=id_, name=name, amount_cents=amount_cents, direction=direction,
        frequency=frequency, day=day, category=category, person=person, effect=effect,
        original_amount_cents=original_amount_cents,
    )


def _cat(obj):
    return Category.model_validate(obj) if obj is not None else None


def _person(obj):
    return Person.model_validate(obj) if obj is not None else None


def _recurring_rows(db, month, mon, filters, *, normalized: bool) -> List[dict]:
    """Recurring contributions for the month.

    normalized=False -> only items whose cadence actually lands this month,
                        at face amount (true cash flow).
    normalized=True  -> every active/in-bounds item, amount divided by its
                        cadence interval (a smoothed per-month figure).
    """
    rows = []
    for item in db.query(models.RecurringItem).all():
        if not _active_in_month(item, month):
            continue
        if not _passes_filters(item.person_id, item.category_id, *filters):
            continue
        if normalized:
            interval = FREQUENCY_MONTHS.get(item.frequency, 1)
            amount = round(item.amount_cents / interval)
        else:
            if not _cadence_hits(item.frequency, item.anchor_month, mon):
                continue
            amount = item.amount_cents
        rows.append(_row(
            "recurring", item.id, item.name, amount, item.direction,
            frequency=item.frequency, day=item.day_of_month,
            category=_cat(item.category), person=_person(item.person),
        ))
    return rows


def _txn_rows(db, start, end, filters) -> List[dict]:
    rows = []
    q = db.query(models.Transaction).filter(
        models.Transaction.date >= start, models.Transaction.date <= end
    )
    for txn in q.all():
        if not _passes_filters(txn.person_id, txn.category_id, *filters):
            continue
        rows.append(_row(
            "transaction", txn.id, txn.description, txn.amount_cents, txn.direction,
            day=txn.date.day, category=_cat(txn.category), person=_person(txn.person),
        ))
    return rows


def _apply_scenario(db, base_rows, adjustments, mon, filters, *, normalized: bool) -> List[dict]:
    """Return a fresh row list with the scenario's adjustments applied.

    `remove`d rows are kept but flagged effect="removed" (and excluded from
    totals) so the UI can show what was taken out.
    """
    rows = [dict(r) for r in base_rows]
    by_recurring_id = {r["id"]: r for r in rows if r["kind"] == "recurring"}

    for adj in adjustments:
        if adj.kind == "remove":
            target = by_recurring_id.get(adj.target_recurring_id)
            if target is not None:
                target["effect"] = "removed"
        elif adj.kind == "modify":
            target = by_recurring_id.get(adj.target_recurring_id)
            if target is None or target["effect"] == "removed":
                continue
            original = target["amount_cents"]
            if adj.override_amount_cents is not None:
                # `original` is already normalized (divided) when normalized=True,
                # so divide the override the same way to stay comparable.
                interval = FREQUENCY_MONTHS.get(target.get("frequency") or "monthly", 1)
                new_amount = (
                    round(adj.override_amount_cents / interval)
                    if normalized
                    else adj.override_amount_cents
                )
            else:
                new_amount = round(original * adj.multiplier)
            target["amount_cents"] = new_amount
            target["original_amount_cents"] = original
            target["effect"] = "modified"
        elif adj.kind == "add":
            if not _passes_filters(adj.person_id, adj.category_id, *filters):
                continue
            freq = adj.frequency or "monthly"
            if normalized:
                interval = FREQUENCY_MONTHS.get(freq, 1)
                amount = round(adj.amount_cents / interval)
            else:
                if not _cadence_hits(freq, adj.anchor_month, mon):
                    continue
                amount = adj.amount_cents
            cat = db.get(models.Category, adj.category_id) if adj.category_id else None
            per = db.get(models.Person, adj.person_id) if adj.person_id else None
            rows.append(_row(
                "recurring", -adj.id, adj.name, amount, adj.direction,
                frequency=freq, day=None, category=_cat(cat), person=_person(per),
                effect="added",
            ))
    return rows


def _split_and_total(rows: List[dict]) -> tuple:
    money_in = sorted(
        [r for r in rows if r["direction"] == "in"],
        key=lambda r: (r["day"] is None, r["day"] or 0, r["name"].lower()),
    )
    money_out = sorted(
        [r for r in rows if r["direction"] == "out"],
        key=lambda r: (r["day"] is None, r["day"] or 0, r["name"].lower()),
    )
    in_cents = sum(r["amount_cents"] for r in money_in if r["effect"] != "removed")
    out_cents = sum(r["amount_cents"] for r in money_out if r["effect"] != "removed")
    totals = MonthTotals(in_cents=in_cents, out_cents=out_cents, net_cents=in_cents - out_cents)
    return money_in, money_out, totals


def _side(actual_rows: List[dict], normalized_rows: List[dict]) -> MonthSide:
    money_in, money_out, totals = _split_and_total(actual_rows)
    _, _, norm_totals = _split_and_total(normalized_rows)
    return MonthSide(
        money_in=[MonthRow(**r) for r in money_in],
        money_out=[MonthRow(**r) for r in money_out],
        totals=totals,
        normalized=norm_totals,
    )


def compute_month(
    db: Session,
    month: str,
    person_id: Optional[int] = None,
    joint_only: bool = False,
    category_ids: Optional[List[int]] = None,
    scenario_id: Optional[int] = None,
) -> MonthResult:
    year, mon, start, end = _month_parts(month)
    filters = (person_id, joint_only, category_ids)

    actual = _recurring_rows(db, month, mon, filters, normalized=False) + _txn_rows(
        db, start, end, filters
    )
    normalized = _recurring_rows(db, month, mon, filters, normalized=True) + _txn_rows(
        db, start, end, filters
    )

    side = _side(actual, normalized)
    result = MonthResult(month=month, **side.model_dump())

    if scenario_id is not None:
        scenario = db.get(models.Scenario, scenario_id)
        if scenario is not None:
            adjustments = scenario.adjustments
            s_actual = _apply_scenario(db, actual, adjustments, mon, filters, normalized=False)
            s_normalized = _apply_scenario(
                db, normalized, adjustments, mon, filters, normalized=True
            )
            s_side = _side(s_actual, s_normalized)
            base_t = side.totals
            scen_t = s_side.totals
            result.scenario = ScenarioMonthResult(
                id=scenario.id,
                name=scenario.name,
                delta=MonthTotals(
                    in_cents=scen_t.in_cents - base_t.in_cents,
                    out_cents=scen_t.out_cents - base_t.out_cents,
                    net_cents=scen_t.net_cents - base_t.net_cents,
                ),
                **s_side.model_dump(),
            )

    return result
