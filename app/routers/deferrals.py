from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..services import deferrals as svc

router = APIRouter(prefix="/api/deferrals", tags=["deferrals"])


@router.post("", response_model=schemas.DeferralOut, status_code=201)
def create_deferral(body: schemas.DeferralCreate, db: Session = Depends(get_db)):
    """Mark a payment as not made this month (rolls into the next), or carry
    an already-carried line forward once more."""
    try:
        if body.origin_id is not None:
            return svc.carry_again(db, body.origin_id)
        if body.transaction_id is not None:
            return svc.defer_transaction(db, body.transaction_id)
        return svc.defer_payment(db, body.recurring_item_id, body.month)
    except svc.DeferralError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.delete("/{deferral_id}", status_code=204)
def undo_deferral(deferral_id: int, db: Session = Depends(get_db)):
    if not svc.undo_deferral(db, deferral_id):
        raise HTTPException(status_code=404, detail="Deferral not found")
    return Response(status_code=204)
