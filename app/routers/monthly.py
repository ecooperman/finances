from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..services.monthly import compute_month

router = APIRouter(prefix="/api", tags=["monthly"])


@router.get("/monthly", response_model=schemas.MonthResult)
def monthly_view(
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    person_id: Optional[int] = Query(None, description="restrict to one person"),
    joint: bool = Query(False, description="restrict to joint / untagged rows only"),
    category_ids: Optional[List[int]] = Query(None, description="repeatable; restrict to these categories"),
    scenario_id: Optional[int] = Query(None, description="overlay a saved scenario"),
    db: Session = Depends(get_db),
):
    if not month:
        today = date.today()
        month = f"{today.year:04d}-{today.month:02d}"
    try:
        year, mon = (int(p) for p in month.split("-"))
        date(year, mon, 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="month must be 'YYYY-MM'")

    return compute_month(
        db,
        month,
        person_id=person_id,
        joint_only=joint,
        category_ids=category_ids,
        scenario_id=scenario_id,
    )
