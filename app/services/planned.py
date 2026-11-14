"""A list or trip planned into a scenario (add_kind="planned"): what it costs and whether the scenario
should count it at all. Shared by the monthly maths (services/monthly.py, which spreads the cost) and
the scenario's "Total cost" summary (which adds up the lump sums)."""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from . import linked_lists as lists_service
from . import trips as trips_service
from .funds import current_month


def planned_cost(db: Session, adj, as_of_month: str) -> Optional[Tuple[int, Optional[str]]]:
    """(amount_cents, live_name) for a planned adjustment: the override if it has one, else the list's
    still-to-buy or the trip's cost, read live. None when the real budget already counts it as an
    upcoming cost (the scenario would be counting it twice, so it adds nothing). The name is None
    when the list or trip is no longer reported."""
    if adj.link_kind == "list":
        if any(r["list_id"] == adj.link_id for r in lists_service.list_forecasts(db, as_of_month)["upcoming"]):
            return None
        cost = next((c for c in (lists_service.fetch_list_costs() or []) if c["id"] == adj.link_id), None)
        computed, name = (cost["to_buy_cents"], cost["name"]) if cost else (0, None)
    else:
        if any(r["trip_id"] == adj.link_id for r in trips_service.trip_forecasts(db, as_of_month)["upcoming"]):
            return None
        trip = next((t for t in trips_service.fetch_trip_costs() if t["id"] == adj.link_id), None)
        computed, name = (trip.get("total_cost_cents", 0), trip["location"]) if trip else (0, None)
    amount = adj.override_amount_cents if adj.override_amount_cents is not None else computed
    return amount, name


def planned_summary(db: Session, adjustments: List) -> dict:
    """What a scenario's planned lists and trips add up to, as lump sums: how many count, their total, and
    the total by the month each is due. Only ones that cost something and that the real budget is not
    already counting - the same ones the monthly maths adds."""
    as_of = current_month()
    months: dict = {}
    total = count = 0
    for adj in adjustments:
        if adj.kind != "add" or adj.add_kind != "planned" or adj.date is None:
            continue
        found = planned_cost(db, adj, as_of)
        if found is None or found[0] <= 0:
            continue
        count += 1
        total += found[0]
        month = adj.date.strftime("%Y-%m")
        months[month] = months.get(month, 0) + found[0]
    return {
        "count": count,
        "cost_cents": total,
        "by_month": [{"month": m, "out_cents": c, "in_cents": 0} for m, c in sorted(months.items())],
    }
