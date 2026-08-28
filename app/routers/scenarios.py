from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..deps import get_db

router = APIRouter(prefix="/api", tags=["scenarios"])


@router.get("/scenarios", response_model=List[schemas.Scenario])
def list_scenarios(db: Session = Depends(get_db)):
    return crud.get_scenarios(db)


@router.get("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def get_scenario(scenario_id: int, db: Session = Depends(get_db)):
    scenario = crud.get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.post("/scenarios", response_model=schemas.Scenario)
def create_scenario(scenario: schemas.ScenarioCreate, db: Session = Depends(get_db)):
    return crud.create_scenario(db, scenario)


@router.patch("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def update_scenario(
    scenario_id: int, updates: schemas.ScenarioUpdate, db: Session = Depends(get_db)
):
    scenario = crud.update_scenario(db, scenario_id, updates)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)):
    if not crud.delete_scenario(db, scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"ok": True}


@router.post("/scenarios/{scenario_id}/adjustments", response_model=schemas.ScenarioAdjustment)
def add_adjustment(
    scenario_id: int, adj: schemas.ScenarioAdjustmentCreate, db: Session = Depends(get_db)
):
    if crud.get_scenario(db, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return crud.add_adjustment(db, scenario_id, adj)


@router.patch("/adjustments/{adjustment_id}", response_model=schemas.ScenarioAdjustment)
def update_adjustment(
    adjustment_id: int, adj: schemas.ScenarioAdjustmentUpdate, db: Session = Depends(get_db)
):
    updated = crud.update_adjustment(db, adjustment_id, adj)
    if updated is None:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return updated


@router.delete("/adjustments/{adjustment_id}")
def delete_adjustment(adjustment_id: int, db: Session = Depends(get_db)):
    if not crud.delete_adjustment(db, adjustment_id):
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return {"ok": True}
