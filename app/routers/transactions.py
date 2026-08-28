from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..deps import get_db

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("", response_model=List[schemas.Transaction])
def list_transactions(
    month: Optional[str] = Query(None, description="YYYY-MM; shorthand for date_from/date_to"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    person_id: Optional[int] = None,
    category_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if month:
        try:
            year, mon = (int(p) for p in month.split("-"))
            from calendar import monthrange

            date_from = date(year, mon, 1)
            date_to = date(year, mon, monthrange(year, mon)[1])
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="month must be 'YYYY-MM'")
    return crud.get_transactions(
        db,
        date_from=date_from,
        date_to=date_to,
        person_id=person_id,
        category_id=category_id,
    )


@router.post("", response_model=schemas.Transaction)
def create_transaction(txn: schemas.TransactionCreate, db: Session = Depends(get_db)):
    return crud.create_transaction(db, txn)


@router.patch("/{txn_id}", response_model=schemas.Transaction)
def update_transaction(
    txn_id: int, updates: schemas.TransactionUpdate, db: Session = Depends(get_db)
):
    txn = crud.update_transaction(db, txn_id, updates)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.delete("/{txn_id}")
def delete_transaction(txn_id: int, db: Session = Depends(get_db)):
    if not crud.delete_transaction(db, txn_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"ok": True}


@router.post("/{txn_id}/convert-to-recurring", response_model=schemas.RecurringItem)
def convert_to_recurring(
    txn_id: int, opts: schemas.ConvertToRecurring, db: Session = Depends(get_db)
):
    item = crud.convert_transaction_to_recurring(db, txn_id, opts)
    if item is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return item
