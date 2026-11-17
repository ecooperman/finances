from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from shared_python import accounts_gate
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..deps import get_db
from ..services import linked_lists as lists_service
from ..services import trips as trips_service
from ..services.funds import current_month
from ..services.linked_lists import list_forecasts
from ..services.planned import planned_summary
from ..services.trips import trip_forecasts

router = APIRouter(prefix="/api", tags=["scenarios"])


def _only_an_administrator_may_plan_lists_and_trips(request: Request, adj) -> None:
    """A planned list or trip is read from the ADMINISTRATOR's lists and trips apps, so nobody else may plan one."""
    if getattr(adj, "add_kind", None) == "planned" and not accounts_gate.current_account(request).is_admin:
        raise HTTPException(status_code=403, detail="Only an administrator can plan a list or a trip")


def _with_planned(db: Session, scenario):
    """Attach the live planned-lists-and-trips summary the response carries (None passes through)."""
    if scenario is not None:
        scenario.planned = planned_summary(db, scenario.adjustments)
    return scenario


@router.get("/scenarios", response_model=List[schemas.Scenario])
def list_scenarios(db: Session = Depends(get_db)):
    return [_with_planned(db, s) for s in crud.get_scenarios(db)]


@router.get("/scenarios/plannable", response_model=List[schemas.PlannableItem])
def plannable(db: Session = Depends(get_db)):
    """The lists and trips that can be linked into a scenario: those the real budget is not already
    counting (it would count twice) and that are not already paid. Declared before
    /scenarios/{scenario_id} so "plannable" is not taken for an id."""
    as_of = current_month()
    counted_lists = {r["list_id"] for r in list_forecasts(db, as_of)["upcoming"]}
    counted_trips = {r["trip_id"] for r in trip_forecasts(db, as_of)["upcoming"]}
    settled_lists = {l.list_id for l in db.query(models.LinkedList).filter(models.LinkedList.settled_at.isnot(None))}
    settled_trips = {s.trip_id for s in db.query(models.TripSettlement).filter(models.TripSettlement.settled_at.isnot(None))}
    items = []
    for c in lists_service.fetch_list_costs() or []:
        if c["id"] not in counted_lists and c["id"] not in settled_lists:
            items.append({"kind": "list", "id": c["id"], "name": c["name"], "amount_cents": c["to_buy_cents"], "due_date": None})
    for t in trips_service.fetch_trip_costs():
        if t["id"] not in counted_trips and t["id"] not in settled_trips:
            start = t.get("start_date")
            items.append({
                "kind": "trip", "id": t["id"], "name": t["location"],
                "amount_cents": t.get("total_cost_cents", 0), "due_date": start[:10] if start else None,
            })
    return items


@router.get("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def get_scenario(scenario_id: int, db: Session = Depends(get_db)):
    scenario = crud.get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _with_planned(db, scenario)


@router.post("/scenarios", response_model=schemas.Scenario)
def create_scenario(scenario: schemas.ScenarioCreate, db: Session = Depends(get_db)):
    return _with_planned(db, crud.create_scenario(db, scenario))


@router.patch("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def update_scenario(
    scenario_id: int, updates: schemas.ScenarioUpdate, db: Session = Depends(get_db)
):
    scenario = crud.update_scenario(db, scenario_id, updates)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _with_planned(db, scenario)


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)):
    if not crud.delete_scenario(db, scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"ok": True}


@router.post("/scenarios/{scenario_id}/adjustments", response_model=schemas.ScenarioAdjustment)
def add_adjustment(
    scenario_id: int, adj: schemas.ScenarioAdjustmentCreate, request: Request, db: Session = Depends(get_db)
):
    _only_an_administrator_may_plan_lists_and_trips(request, adj)
    if crud.get_scenario(db, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return crud.add_adjustment(db, scenario_id, adj)


@router.patch("/adjustments/{adjustment_id}", response_model=schemas.ScenarioAdjustment)
def update_adjustment(
    adjustment_id: int, adj: schemas.ScenarioAdjustmentUpdate, request: Request, db: Session = Depends(get_db)
):
    _only_an_administrator_may_plan_lists_and_trips(request, adj)
    updated = crud.update_adjustment(db, adjustment_id, adj)
    if updated is None:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return updated


@router.delete("/adjustments/{adjustment_id}")
def delete_adjustment(adjustment_id: int, db: Session = Depends(get_db)):
    if not crud.delete_adjustment(db, adjustment_id):
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return {"ok": True}
