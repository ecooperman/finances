from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db
from ..services.daily import daily_budget

router = APIRouter(prefix="/api", tags=["daily"])


@router.get("/daily-budget", response_model=schemas.DailyBudget)
def get_daily_budget(
    on: Optional[date] = Query(None, description="YYYY-MM-DD; default today"),
    person_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Where each daily-spread item stands as of a day (the Today card)."""
    on = on or date.today()
    return {"as_of": on, "items": daily_budget(db, on, person_id=person_id)}


@router.post("/daily-spend", response_model=schemas.DailySpendOut, status_code=201)
def log_daily_spend(body: schemas.DailySpendCreate, db: Session = Depends(get_db)):
    """Log one real cost against a daily-spread item on a day."""
    item = db.get(models.RecurringItem, body.recurring_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    if not item.spread_daily:
        raise HTTPException(status_code=400, detail="That item isn't spread across every day")
    row = models.DailySpend(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/daily-spend/{spend_id}", response_model=schemas.DailySpendOut)
def update_daily_spend(spend_id: int, body: schemas.DailySpendUpdate, db: Session = Depends(get_db)):
    row = db.get(models.DailySpend, spend_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "amount_cents" and value is None:
            continue
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/daily-spend/{spend_id}", status_code=204)
def delete_daily_spend(spend_id: int, db: Session = Depends(get_db)):
    row = db.get(models.DailySpend, spend_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
