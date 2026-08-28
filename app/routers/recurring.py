from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..deps import get_db
from ..models import FREQUENCY_MONTHS

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.get("", response_model=List[schemas.RecurringItem])
def list_recurring(
    person_id: Optional[int] = None,
    category_id: Optional[int] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    return crud.get_recurring_items(db, person_id=person_id, category_id=category_id, active=active)


@router.get("/summary")
def recurring_summary(db: Session = Depends(get_db)):
    """The known monthly baseline: totals of all active recurring items,
    with lumpy (non-monthly) items smoothed to a per-month figure."""
    items = crud.get_recurring_items(db, active=True)
    in_cents = out_cents = 0
    for item in items:
        interval = FREQUENCY_MONTHS.get(item.frequency, 1)
        per_month = round(item.amount_cents / interval)
        if item.direction == "in":
            in_cents += per_month
        else:
            out_cents += per_month
    return {
        "in_cents": in_cents,
        "out_cents": out_cents,
        "net_cents": in_cents - out_cents,
        "item_count": len(items),
    }


@router.post("", response_model=schemas.RecurringItem)
def create_recurring(item: schemas.RecurringItemCreate, db: Session = Depends(get_db)):
    return crud.create_recurring_item(db, item)


@router.patch("/{item_id}", response_model=schemas.RecurringItem)
def update_recurring(
    item_id: int, updates: schemas.RecurringItemUpdate, db: Session = Depends(get_db)
):
    item = crud.update_recurring_item(db, item_id, updates)
    if item is None:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return item


@router.delete("/{item_id}")
def delete_recurring(item_id: int, db: Session = Depends(get_db)):
    if not crud.delete_recurring_item(db, item_id):
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return {"ok": True}


@router.post("/{item_id}/convert-to-transaction", response_model=schemas.Transaction)
def convert_to_transaction(
    item_id: int, body: schemas.ConvertToTransaction, db: Session = Depends(get_db)
):
    txn = crud.convert_recurring_to_transaction(db, item_id, body.date)
    if txn is None:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return txn
