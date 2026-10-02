from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..services.paycheck import until_next_paycheck

router = APIRouter(prefix="/api", tags=["paycheck"])


@router.get("/until-paycheck", response_model=schemas.UntilPaycheck)
def until_paycheck(
    on: Optional[date] = Query(None, description="YYYY-MM-DD to look ahead from; default today"),
    person_id: Optional[int] = Query(None, description="only count this person's income as the paycheck"),
    db: Session = Depends(get_db),
):
    return until_next_paycheck(db, on or date.today(), person_id=person_id)
