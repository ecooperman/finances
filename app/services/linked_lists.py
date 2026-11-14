"""Linked lists - a list from the lists app, forecast as one lump sum exactly like a trip.

A list that tracks costs can be linked into the budget. Its cost is the list's "still to buy" total,
fetched live from the lists app (every ~30s) and never stored here: priced items that are not left
out of the list's totals and not ticked done (done items are already spent and belong in real
transactions). The date is picked when linking - lists have none of their own - and the cost is then
spread over the months until it, by the same rule trips use (services/forecast.py). Finances stores
only its own state per linked list (`LinkedList`): the date, excluded, an override amount, and whether
it has been marked fully paid.
"""

import logging
import time
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from .. import models
from ..config import LISTS_API_BASE, LISTS_SERVICE_TOKEN
from .forecast import place
from .funds import current_month

log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30
_cache = {"at": 0.0, "data": None}


def fetch_list_costs() -> Optional[List[dict]]:
    """`GET {LISTS_API_BASE}/api/lists/cost-summary`, cached for 30s. Returns None (never raises) if the
    lists app is unreachable or refuses the call - which is different from an empty list, so a linked
    list is shown as "not found" rather than quietly dropped from the forecast."""
    now = time.monotonic()
    if _cache["at"] and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["data"]
    try:
        headers = {"X-Service-Token": LISTS_SERVICE_TOKEN} if LISTS_SERVICE_TOKEN else {}
        resp = httpx.get(f"{LISTS_API_BASE}/api/lists/cost-summary", headers=headers, timeout=2.0)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("cost-summary did not return a list")
    except Exception as exc:  # noqa: BLE001 - any failure = "lists unavailable"
        log.warning("list cost fetch failed (%s): %s", LISTS_API_BASE, exc)
        data = None
    _cache["at"] = now
    _cache["data"] = data
    return data


def clear_cache() -> None:
    _cache["at"] = 0.0
    _cache["data"] = None


def _month(link: models.LinkedList) -> Optional[str]:
    return link.due_date.strftime("%Y-%m") if link.due_date else None


def list_forecasts(db: Session, as_of_month: Optional[str] = None) -> dict:
    """{"upcoming": [...], "no_date": [...], "excluded": [...], "available": [...], "reachable": bool}.

    Only `upcoming` feeds the monthly provisioning math. `no_date` and `excluded` are shown but
    contribute nothing; marked-paid lists are dropped (their cost is a real transaction now).
    `available` are the lists that track costs and are not linked yet (for the "Link a list" picker).
    A linked list the lists app does not report (deleted, no longer tracking costs, or lists is
    unreachable) stays in its bucket flagged `missing`, counted at its override if it has one."""
    as_of_month = as_of_month or current_month()
    costs = fetch_list_costs()
    by_id = {c["id"]: c for c in (costs or [])}
    links = db.query(models.LinkedList).order_by(models.LinkedList.id).all()

    buckets = {"upcoming": [], "no_date": [], "excluded": []}
    for link in links:
        if link.settled_at is not None:
            continue
        cost = by_id.get(link.list_id)
        computed = cost["to_buy_cents"] if cost else 0
        amount = link.override_amount_cents if link.override_amount_cents is not None else computed
        row = {
            "list_id": link.list_id,
            "name": cost["name"] if cost else link.name,
            "due_date": link.due_date.isoformat() if link.due_date else None,
            "total_cents": amount,
            "override_amount_cents": link.override_amount_cents,
            "computed_total_cents": computed,
            "excluded": bool(link.excluded),
            "settled_at": None,
            "missing": cost is None,
            "note": link.note,
            "bought_cents": cost["bought_cents"] if cost else 0,
            "excluded_count": cost["excluded_count"] if cost else 0,
            "unpriced_count": cost["unpriced_count"] if cost else 0,
        }
        bucket = place(
            row, amount=amount, month=_month(link), excluded=row["excluded"], as_of_month=as_of_month, month_key="due_month"
        )
        buckets[bucket].append(row)

    buckets["upcoming"].sort(key=lambda r: r["due_month"])
    linked_ids = {link.list_id for link in links}
    buckets["available"] = [
        {"list_id": c["id"], "name": c["name"], "to_buy_cents": c["to_buy_cents"]}
        for c in (costs or [])
        if c["id"] not in linked_ids
    ]
    buckets["reachable"] = costs is not None
    return buckets


def lists_summary(db: Session, as_of_month: Optional[str] = None) -> dict:
    fc = list_forecasts(db, as_of_month)
    linked = len(fc["upcoming"]) + len(fc["no_date"]) + len(fc["excluded"])
    return {
        "upcoming_count": len(fc["upcoming"]) + len(fc["no_date"]),
        "monthly_total_cents": sum(r["monthly_contribution_cents"] for r in fc["upcoming"]),
        # unreachable only matters once something is linked
        "reachable": fc["reachable"] or linked == 0,
    }
