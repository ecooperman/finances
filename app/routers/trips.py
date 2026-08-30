from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..deps import get_db
from ..services.funds import current_month
from ..services.trips import fetch_trip_costs, trip_forecasts, trips_summary

router = APIRouter(prefix="/api/trips", tags=["trips"])


def _travel_category_id(db: Session):
    """A category to hang a settled trip's transaction on: "Travel" if it
    exists, else "Transportation", else nothing."""
    for name in ("Travel", "Transportation"):
        cat = db.query(models.Category).filter(models.Category.name == name).first()
        if cat is not None:
            return cat.id
    return None


@router.get("", response_model=schemas.TripForecasts)
def list_trip_forecasts(
    month: Optional[str] = Query(None, description="YYYY-MM to spread costs as of; default now"),
    db: Session = Depends(get_db),
):
    return trip_forecasts(db, month or current_month())


@router.get("/summary", response_model=schemas.TripsSummary)
def summary(
    month: Optional[str] = Query(None, description="YYYY-MM; default now"),
    db: Session = Depends(get_db),
):
    return trips_summary(db, month or current_month())


@router.patch("/{trip_id}")
def update_trip_settlement(
    trip_id: int, updates: schemas.TripSettlementUpdate, db: Session = Depends(get_db)
):
    s = crud.update_settlement(db, trip_id, updates)
    return {
        "trip_id": s.trip_id,
        "excluded": s.excluded,
        "override_amount_cents": s.override_amount_cents,
        "settled_at": s.settled_at.isoformat() if s.settled_at else None,
    }


@router.post("/{trip_id}/settle")
def settle_trip(trip_id: int, body: schemas.SettleTripRequest, db: Session = Depends(get_db)):
    trip = next((t for t in fetch_trip_costs() if t["id"] == trip_id), None)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found in trip-planning")
    settlement = crud.get_settlement(db, trip_id)
    override = settlement.override_amount_cents if settlement is not None else None
    amount = body.amount_cents or override or trip.get("total_cost_cents", 0)
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="No trip cost to settle - set an amount, or a cost in trip-planning.",
        )
    s = crud.settle_trip(
        db, trip_id, body.date, amount, trip["location"], _travel_category_id(db)
    )
    return {
        "trip_id": s.trip_id,
        "settled_at": s.settled_at.isoformat() if s.settled_at else None,
        "settled_transaction_id": s.settled_transaction_id,
    }


@router.post("/{trip_id}/unsettle")
def unsettle_trip(trip_id: int, db: Session = Depends(get_db)):
    s = crud.unsettle_trip(db, trip_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Trip was not settled")
    return {"ok": True}
