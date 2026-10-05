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
from ..models import FREQUENCY_INTERVAL_MONTHS, FREQUENCY_PER_MONTH
from .funds import monthly_contribution_cents
from . import balance as balance_svc
from . import daily as daily_svc
from .schedule import active_in_month, cadence_hits, daily_amounts, occurrence_days, shift_month
from .trips import trip_forecasts
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


def _recurring_amount(frequency: str, face_cents: int, normalized: bool) -> int:
    """The amount a recurring item contributes to one month.

    - sub-monthly (quarterly/...): its full face amount on the month it
      lands (normalized=False), or its face / interval every month
      (normalized=True).
    - weekly/biweekly/monthly: the per-month figure either way
      (face * occurrences-per-month; == face for monthly).
    """
    if not normalized and frequency in FREQUENCY_INTERVAL_MONTHS:
        return face_cents
    return round(face_cents * FREQUENCY_PER_MONTH.get(frequency, 1.0))


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
         occurrence_days=None, face_amount_cents=None, category=None, person=None,
         effect="normal", original_amount_cents=None, notes=None, reference_id=None,
         account_name=None, start_month=None, end_month=None, day_of_week=None,
         deferral_id=None, deferred_to=None, carried_from=None, carry_source_id=None,
         daily=None) -> dict:
    return dict(
        kind=kind, id=id_, name=name, amount_cents=amount_cents, direction=direction,
        frequency=frequency, day=day, occurrence_days=occurrence_days,
        face_amount_cents=face_amount_cents, category=category, person=person,
        effect=effect, original_amount_cents=original_amount_cents, notes=notes,
        reference_id=reference_id, account_name=account_name, start_month=start_month,
        end_month=end_month, day_of_week=day_of_week, deferral_id=deferral_id,
        deferred_to=deferred_to, carried_from=carried_from, carry_source_id=carry_source_id,
        daily=daily,
    )


def _cat(obj):
    return Category.model_validate(obj) if obj is not None else None


def _person(obj):
    return Person.model_validate(obj) if obj is not None else None


def _weekly_days(item, year: int, mon: int):
    """Real pay days this month for a weekly/biweekly item (None if it
    isn't one, or has no weekday set) - the calendar draws one entry per
    day at the item's face amount."""
    if item.frequency not in ("weekly", "biweekly"):
        return None
    return occurrence_days(
        item.frequency, item.day_of_month, item.day_of_week, item.week_anchor, year, mon
    )


def _recurring_rows(db, month, mon, filters, *, normalized: bool) -> List[dict]:
    """Recurring contributions for the month.

    normalized=False -> only items whose cadence lands this month, at their
                        month's contribution (true cash flow). Weekly/biweekly
                        items with a weekday set count once per real pay day.
    normalized=True  -> every active/in-bounds item, its smoothed per-month
                        figure.
    """
    rows = []
    year = int(month[:4])
    spend = daily_svc.month_spend(db, year, mon) if not normalized else {}
    for item in db.query(models.RecurringItem).all():
        if not active_in_month(item, month):
            continue
        if not _passes_filters(item.person_id, item.category_id, *filters):
            continue
        if not normalized and not cadence_hits(item.frequency, item.anchor_month, mon):
            continue
        days = _weekly_days(item, year, mon)
        daily = None
        if not normalized and item.spread_daily:
            # one allowance per day; the month counts each day's logged
            # spend (or its allowance if nothing is logged)
            daily = daily_svc.build_days(item.amount_cents, year, mon, spend.get(item.id))
            amount = daily_svc.month_total(daily)
        elif not normalized and days is not None:
            # cash flow counts the real pay days (a 3-paycheck month is 3x)
            amount = item.amount_cents * len(days)
        else:
            amount = _recurring_amount(item.frequency, item.amount_cents, normalized)
        rows.append(_row(
            "recurring", item.id, item.name, amount, item.direction,
            frequency=item.frequency, day=None if item.spread_daily else item.day_of_month,
            occurrence_days=days, daily=daily,
            face_amount_cents=item.amount_cents,
            notes=item.notes, reference_id=item.reference_id,
            start_month=item.start_month, end_month=item.end_month,
            day_of_week=item.day_of_week,
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
            day=txn.date.day, notes=txn.notes, account_name=txn.account_name,
            category=_cat(txn.category), person=_person(txn.person),
        ))
    return rows


def _fund_rows(db, filters) -> List[dict]:
    """Provisioning-only rows: each active sinking fund's flat monthly
    set-aside, on the `out` side. Never part of the cash-flow figure."""
    rows = []
    for fund in db.query(models.SinkingFund).filter(models.SinkingFund.active.is_(True)).all():
        if not _passes_filters(fund.person_id, fund.category_id, *filters):
            continue
        rows.append(_row(
            "fund", fund.id, fund.name, monthly_contribution_cents(fund), "out",
            category=_cat(fund.category), person=_person(fund.person),
        ))
    return rows


def _trip_rows(db, month, filters) -> List[dict]:
    """Provisioning-only rows: each upcoming trip's cost spread over the
    months until it happens (cost read live from trip-planning). Household /
    no category, so dropped by a person or category filter."""
    if not _passes_filters(None, None, *filters):
        return []
    rows = []
    for t in trip_forecasts(db, month)["upcoming"]:
        if t["monthly_contribution_cents"] <= 0:
            continue
        rows.append(_row(
            "trip", t["trip_id"], t["name"], t["monthly_contribution_cents"], "out",
        ))
    return rows


def _apply_scenario(db, base_rows, adjustments, mon, filters, *, normalized: bool) -> List[dict]:
    """Return a fresh row list with the scenario's adjustments applied.

    `remove`d rows are kept but flagged effect="removed" (and excluded from
    totals) so the UI can show what was taken out.
    """
    rows = [dict(r) for r in base_rows]
    by_recurring_id = {r["id"]: r for r in rows if r["kind"] == "recurring"}
    by_fund_id = {r["id"]: r for r in rows if r["kind"] == "fund"}

    for adj in adjustments:
        is_fund = adj.target_fund_id is not None or (
            adj.kind == "add" and getattr(adj, "add_kind", "recurring") == "fund"
        )
        # Fund adjustments only move the provisioning figure, never cash flow.
        if is_fund and not normalized:
            continue

        if adj.kind == "remove":
            target = (
                by_fund_id.get(adj.target_fund_id)
                if is_fund
                else by_recurring_id.get(adj.target_recurring_id)
            )
            if target is not None and target["effect"] != "deferred":
                target["effect"] = "removed"

        elif adj.kind == "modify":
            target = (
                by_fund_id.get(adj.target_fund_id)
                if is_fund
                else by_recurring_id.get(adj.target_recurring_id)
            )
            if target is None or target["effect"] in ("removed", "deferred"):
                continue
            original = target["amount_cents"]
            if adj.override_amount_cents is not None:
                if is_fund:
                    # override is an annual amount; row holds the monthly set-aside
                    new_amount = round(adj.override_amount_cents / 12)
                elif not normalized and target.get("occurrence_days") is not None:
                    # cash flow: the override is per payment, paid on each real day
                    new_amount = adj.override_amount_cents * len(target["occurrence_days"])
                else:
                    # the row holds this month's contribution, not the face
                    # amount, so convert the override the same way.
                    new_amount = _recurring_amount(
                        target.get("frequency") or "monthly",
                        adj.override_amount_cents,
                        normalized,
                    )
            else:
                new_amount = round(original * adj.multiplier)
            target["amount_cents"] = new_amount
            target["original_amount_cents"] = original
            if not is_fund and not normalized and target.get("daily") is not None:
                # the scenario changes the plan; real logged costs stay
                new_face = (adj.override_amount_cents if adj.override_amount_cents is not None
                            else round(target["face_amount_cents"] * adj.multiplier))
                allowances = daily_amounts(new_face, len(target["daily"]))
                target["daily"] = [{**d, "allowance_cents": a} for d, a in zip(target["daily"], allowances)]
                target["amount_cents"] = daily_svc.month_total(target["daily"])
            target["effect"] = "modified"
            # keep the per-payment (calendar) amount in step with the change
            if not is_fund and target.get("face_amount_cents") is not None:
                if adj.override_amount_cents is not None:
                    target["face_amount_cents"] = adj.override_amount_cents
                else:
                    target["face_amount_cents"] = round(target["face_amount_cents"] * adj.multiplier)

        elif adj.kind == "add":
            if not _passes_filters(adj.person_id, adj.category_id, *filters):
                continue
            cat = db.get(models.Category, adj.category_id) if adj.category_id else None
            per = db.get(models.Person, adj.person_id) if adj.person_id else None
            if is_fund:
                rows.append(_row(
                    "fund", -adj.id, adj.name, round(adj.amount_cents / 12), "out",
                    category=_cat(cat), person=_person(per), effect="added",
                ))
            else:
                freq = adj.frequency or "monthly"
                if not normalized and not cadence_hits(freq, adj.anchor_month, mon):
                    continue
                amount = _recurring_amount(freq, adj.amount_cents, normalized)
                rows.append(_row(
                    "recurring", -adj.id, adj.name, amount, adj.direction,
                    frequency=freq, day=None, face_amount_cents=adj.amount_cents,
                    category=_cat(cat), person=_person(per), effect="added",
                ))
    return rows


_UNCOUNTED = ("removed", "deferred")


def _deferral_rows(db, month, filters, actual: List[dict]) -> List[dict]:
    """Apply payment deferrals to this month's cash-flow rows.

    - A recurring row whose payment was deferred this month is flagged
      effect="deferred" (kept visible, excluded from the totals).
    - Last month's unpaid payments appear as kind="carryover" lines on the
      1st - counted, unless they were carried forward again.
    """
    deferrals = db.query(models.PaymentDeferral).filter(
        models.PaymentDeferral.month.in_([month, shift_month(month, -1)])
    ).all()
    if not deferrals:
        return actual
    next_month = shift_month(month, 1)
    this_month = [d for d in deferrals if d.month == month]
    regular = {d.recurring_item_id: d for d in this_month
               if d.origin_id is None and d.recurring_item_id is not None}
    regular_txn = {d.transaction_id: d for d in this_month
                   if d.origin_id is None and d.transaction_id is not None}
    carried_on = {d.origin_id: d for d in this_month if d.origin_id is not None}

    for r in actual:
        d = None
        if r["kind"] == "recurring":
            d = regular.get(r["id"])
        elif r["kind"] == "transaction":
            d = regular_txn.get(r["id"])
        if d is not None:
            r["effect"] = "deferred"
            r["deferral_id"] = d.id
            r["deferred_to"] = next_month

    extra = []
    for d in deferrals:
        if d.month != shift_month(month, -1):
            continue
        if d.transaction_id is not None:
            src = db.get(models.Transaction, d.transaction_id)
            name = src.description if src is not None else None
            ref = None
        else:
            src = db.get(models.RecurringItem, d.recurring_item_id)
            name = src.name if src is not None else None
            ref = src.reference_id if src is not None else None
        if src is None or not _passes_filters(src.person_id, src.category_id, *filters):
            continue
        child = carried_on.get(d.id)
        extra.append(_row(
            "carryover", d.id, name, d.amount_cents, src.direction,
            day=1, face_amount_cents=d.amount_cents, notes=src.notes,
            reference_id=ref, category=_cat(src.category),
            person=_person(src.person), carried_from=d.original_month,
            carry_source_id=d.id,
            effect="deferred" if child else "normal",
            deferral_id=child.id if child else None,
            deferred_to=next_month if child else None,
        ))
    return actual + extra


def _split_and_total(rows: List[dict]) -> tuple:
    money_in = sorted(
        [r for r in rows if r["direction"] == "in"],
        key=lambda r: (r["day"] is None, r["day"] or 0, r["name"].lower()),
    )
    money_out = sorted(
        [r for r in rows if r["direction"] == "out"],
        key=lambda r: (r["day"] is None, r["day"] or 0, r["name"].lower()),
    )
    # removed (scenario) and deferred (carried to next month) rows are shown
    # but don't count toward this month.
    in_cents = sum(r["amount_cents"] for r in money_in if r["effect"] not in _UNCOUNTED)
    out_cents = sum(r["amount_cents"] for r in money_out if r["effect"] not in _UNCOUNTED)
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

    # actual = true cash flow this month (recurrings that land + one-offs).
    actual = _recurring_rows(db, month, mon, filters, normalized=False) + _txn_rows(
        db, start, end, filters
    )
    actual = _deferral_rows(db, month, filters, actual)
    # normalized = provisioning: lumpy recurrings smoothed + sinking-fund
    # set-asides + upcoming trips spread over the months until they happen.
    # One-offs are deliberately excluded - an unprovisioned surprise belongs
    # in cash flow, not the "typical month" figure.
    normalized = (
        _recurring_rows(db, month, mon, filters, normalized=True)
        + _fund_rows(db, filters)
        + _trip_rows(db, month, filters)
    )

    side = _side(actual, normalized)
    result = MonthResult(month=month, opening=balance_svc.opening_balance(db, month), **side.model_dump())

    if scenario_id is not None:
        scenario = db.get(models.Scenario, scenario_id)
        if scenario is not None:
            adjustments = scenario.adjustments
            s_actual = _apply_scenario(db, actual, adjustments, mon, filters, normalized=False)
            s_normalized = _apply_scenario(
                db, normalized, adjustments, mon, filters, normalized=True
            )
            s_side = _side(s_actual, s_normalized)

            def _delta(scen: MonthTotals, base: MonthTotals) -> MonthTotals:
                return MonthTotals(
                    in_cents=scen.in_cents - base.in_cents,
                    out_cents=scen.out_cents - base.out_cents,
                    net_cents=scen.net_cents - base.net_cents,
                )

            result.scenario = ScenarioMonthResult(
                id=scenario.id,
                name=scenario.name,
                delta=_delta(s_side.totals, side.totals),
                normalized_delta=_delta(s_side.normalized, side.normalized),
                **s_side.model_dump(),
            )

    return result
