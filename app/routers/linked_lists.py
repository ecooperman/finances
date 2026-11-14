"""Lists linked into the budget as lump-sum planned costs - the same shape as /api/trips (see
services/linked_lists.py). The list id is the key everywhere, like the trip id for trips."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..deps import get_db
from ..services.funds import current_month
from ..services import linked_lists as lists_service
from ..services.linked_lists import list_forecasts, lists_summary

router = APIRouter(prefix="/api/linked-lists", tags=["linked-lists"])


def _state(link):
    return {
        "list_id": link.list_id,
        "due_date": link.due_date.isoformat() if link.due_date else None,
        "excluded": link.excluded,
        "override_amount_cents": link.override_amount_cents,
        "settled_at": link.settled_at.isoformat() if link.settled_at else None,
    }


@router.get("", response_model=schemas.LinkedListForecasts)
def linked_list_forecasts(
    month: Optional[str] = Query(None, description="YYYY-MM to spread costs as of; default now"),
    db: Session = Depends(get_db),
):
    return list_forecasts(db, month or current_month())


@router.get("/summary", response_model=schemas.TripsSummary)
def summary(month: Optional[str] = Query(None, description="YYYY-MM; default now"), db: Session = Depends(get_db)):
    return lists_summary(db, month or current_month())


@router.post("")
def link_list(body: schemas.LinkedListCreate, db: Session = Depends(get_db)):
    costs = lists_service.fetch_list_costs()
    if costs is None:
        raise HTTPException(status_code=502, detail="Could not reach the Lists app - try again in a moment.")
    found = next((c for c in costs if c["id"] == body.list_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="That list was not found, or it does not track costs.")
    return _state(crud.link_list(db, body.list_id, found["name"], body.due_date))


@router.patch("/{list_id}")
def update_link(list_id: int, updates: schemas.LinkedListUpdate, db: Session = Depends(get_db)):
    link = crud.update_linked_list(db, list_id, updates)
    if link is None:
        raise HTTPException(status_code=404, detail="That list is not linked")
    return _state(link)


@router.delete("/{list_id}")
def unlink(list_id: int, db: Session = Depends(get_db)):
    if not crud.unlink_list(db, list_id):
        raise HTTPException(status_code=404, detail="That list is not linked")
    return {"ok": True}


@router.post("/{list_id}/settle")
def settle(list_id: int, body: schemas.SettleTripRequest, db: Session = Depends(get_db)):
    link = crud.get_linked_list(db, list_id)
    if link is None:
        raise HTTPException(status_code=404, detail="That list is not linked")
    row = next(
        (r for bucket in ("upcoming", "no_date", "excluded") for r in list_forecasts(db)[bucket] if r["list_id"] == list_id),
        None,
    )
    amount = body.amount_cents or link.override_amount_cents or (row["computed_total_cents"] if row else 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="No cost to settle - set an amount, or price the list's items in Lists.")
    name = row["name"] if row else link.name
    settled = crud.settle_linked_list(db, list_id, body.date, amount, name)
    return {
        "list_id": list_id,
        "settled_at": settled.settled_at.isoformat() if settled.settled_at else None,
        "settled_transaction_id": settled.settled_transaction_id,
    }


@router.post("/{list_id}/unsettle")
def unsettle(list_id: int, db: Session = Depends(get_db)):
    link = crud.unsettle_linked_list(db, list_id)
    if link is None:
        raise HTTPException(status_code=404, detail="That list was not settled")
    return {"ok": True}
