from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..services import balance as svc

router = APIRouter(prefix="/api/opening-balance", tags=["balance"])

MONTH = Path(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")


@router.get("/{month}", response_model=schemas.OpeningBalance)
def get_opening(month: str = MONTH, db: Session = Depends(get_db)):
    return svc.opening_balance(db, month)


@router.put("/{month}", response_model=schemas.OpeningBalance)
def set_opening(body: schemas.OpeningBalanceSet, month: str = MONTH, db: Session = Depends(get_db)):
    """Override what `month` opens with (your real balance). Later months
    roll forward from it."""
    svc.set_override(db, month, body.amount_cents, body.note)
    return svc.opening_balance(db, month)


@router.delete("/{month}", response_model=schemas.OpeningBalance)
def clear_opening(month: str = MONTH, db: Session = Depends(get_db)):
    """Drop the override: the month goes back to rolling over."""
    if not svc.clear_override(db, month):
        raise HTTPException(status_code=404, detail="No override set for that month")
    return svc.opening_balance(db, month)
