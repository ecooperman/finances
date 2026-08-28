from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..deps import get_db
from ..services.funds import current_month, fund_status, funds_summary

router = APIRouter(prefix="/api/funds", tags=["funds"])


def _with_status(db: Session, fund, as_of_month: str) -> schemas.FundWithStatus:
    base = schemas.Fund.model_validate(fund).model_dump()
    return schemas.FundWithStatus(**base, **fund_status(db, fund, as_of_month))


@router.get("", response_model=List[schemas.FundWithStatus])
def list_funds(
    person_id: Optional[int] = None,
    category_id: Optional[int] = None,
    active: Optional[bool] = None,
    month: Optional[str] = Query(None, description="YYYY-MM to compute balances as of; default now"),
    db: Session = Depends(get_db),
):
    as_of = month or current_month()
    funds = crud.get_funds(db, person_id=person_id, category_id=category_id, active=active)
    return [_with_status(db, f, as_of) for f in funds]


@router.get("/summary", response_model=schemas.FundsSummary)
def summary(
    month: Optional[str] = Query(None, description="YYYY-MM; default now"),
    db: Session = Depends(get_db),
):
    return funds_summary(db, month or current_month())


@router.post("", response_model=schemas.FundWithStatus)
def create_fund(fund: schemas.FundCreate, db: Session = Depends(get_db)):
    db_fund = crud.create_fund(db, fund, default_start_month=current_month())
    return _with_status(db, db_fund, current_month())


@router.patch("/{fund_id}", response_model=schemas.FundWithStatus)
def update_fund(fund_id: int, updates: schemas.FundUpdate, db: Session = Depends(get_db)):
    db_fund = crud.update_fund(db, fund_id, updates)
    if db_fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    return _with_status(db, db_fund, current_month())


@router.delete("/{fund_id}")
def delete_fund(fund_id: int, db: Session = Depends(get_db)):
    if not crud.delete_fund(db, fund_id):
        raise HTTPException(status_code=404, detail="Fund not found")
    return {"ok": True}
