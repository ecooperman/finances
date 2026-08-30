"""Trip cost forecasting - a live read from the trip-planning app.

Each upcoming trip is a forecast-only provisioning line: its cost is spread
evenly over the months from now through the trip's month (a sinking fund
with a deadline). Nothing about the cost is stored here - it's fetched from
trip-planning every ~30s - so it always reflects the current itinerary.
Finances only stores its own per-trip state (`TripSettlement`): excluded,
an override amount, and whether it's been marked fully paid.
"""

import logging
import time
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from .. import models
from ..config import TRIPS_API_BASE
from .funds import current_month, months_elapsed

log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30
_cache = {"at": 0.0, "data": None}


def fetch_trip_costs() -> List[dict]:
    """`GET {TRIPS_API_BASE}/api/trips/cost-summary`, cached for 30s.
    Returns [] (never raises) if trip-planning is unreachable or errors -
    the forecast just shows nothing in that case."""
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["data"]
    try:
        resp = httpx.get(f"{TRIPS_API_BASE}/api/trips/cost-summary", timeout=2.0)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("cost-summary did not return a list")
    except Exception as exc:  # noqa: BLE001 - any failure = "trips unavailable"
        log.warning("trip cost fetch failed (%s): %s", TRIPS_API_BASE, exc)
        data = []
    _cache["at"] = now
    _cache["data"] = data
    return data


def _trip_month(start_date: Optional[str]) -> Optional[str]:
    if not start_date:
        return None
    return start_date[:7]  # "YYYY-MM..." -> "YYYY-MM"


def trip_forecasts(db: Session, as_of_month: Optional[str] = None) -> dict:
    """Returns {"upcoming": [...], "no_date": [...], "excluded": [...]}.

    Only `upcoming` feeds the monthly provisioning math. `no_date` and
    `excluded` are surfaced in the UI (so you can set a date / re-include)
    but contribute nothing. `settled` trips are dropped entirely - their
    cost now lives in cash flow as a real transaction.
    """
    as_of_month = as_of_month or current_month()
    settlements = {s.trip_id: s for s in db.query(models.TripSettlement).all()}

    upcoming, no_date, excluded = [], [], []
    for trip in fetch_trip_costs():
        s = settlements.get(trip["id"])
        if s is not None and s.settled_at is not None:
            continue
        amount = (
            s.override_amount_cents
            if s is not None and s.override_amount_cents is not None
            else trip.get("total_cost_cents", 0)
        )
        row = {
            "trip_id": trip["id"],
            "name": trip["location"],
            "total_cents": amount,
            "override_amount_cents": s.override_amount_cents if s is not None else None,
            "computed_total_cents": trip.get("total_cost_cents", 0),
            "excluded": bool(s.excluded) if s is not None else False,
            "settled_at": s.settled_at.isoformat() if s is not None and s.settled_at else None,
        }
        month = _trip_month(trip.get("start_date"))
        if row["excluded"]:
            row.update(trip_month=month, months_remaining=None, monthly_contribution_cents=0)
            excluded.append(row)
            continue
        if month is None:
            row.update(trip_month=None, months_remaining=None, monthly_contribution_cents=0)
            no_date.append(row)
            continue
        if amount <= 0:
            # keep it visible (so you can set an override) but contribute nothing
            months_remaining = max(months_elapsed(as_of_month, month), 1)
            row.update(
                trip_month=month, months_remaining=months_remaining,
                monthly_contribution_cents=0,
            )
            upcoming.append(row)
            continue
        # months from as_of through the trip's month, inclusive; an overdue
        # or current-month trip is "all due now".
        months_remaining = months_elapsed(as_of_month, month)
        if months_remaining <= 1:
            per_month = amount
            months_remaining = max(months_remaining, 1)
        else:
            per_month = round(amount / months_remaining)
        row.update(
            trip_month=month,
            months_remaining=months_remaining,
            monthly_contribution_cents=per_month,
        )
        upcoming.append(row)

    upcoming.sort(key=lambda r: r["trip_month"])
    return {"upcoming": upcoming, "no_date": no_date, "excluded": excluded}


def trips_summary(db: Session, as_of_month: Optional[str] = None) -> dict:
    fc = trip_forecasts(db, as_of_month)
    return {
        "upcoming_count": len(fc["upcoming"]) + len(fc["no_date"]),
        "monthly_total_cents": sum(r["monthly_contribution_cents"] for r in fc["upcoming"]),
    }
