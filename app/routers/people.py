from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..deps import get_db

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("", response_model=List[schemas.Person])
def list_people(db: Session = Depends(get_db)):
    return crud.get_people(db)


@router.post("", response_model=schemas.Person)
def create_person(person: schemas.PersonCreate, db: Session = Depends(get_db)):
    return crud.create_person(db, person)


@router.patch("/{person_id}", response_model=schemas.Person)
def update_person(person_id: int, updates: schemas.PersonUpdate, db: Session = Depends(get_db)):
    person = crud.update_person(db, person_id, updates)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


@router.delete("/{person_id}")
def delete_person(person_id: int, db: Session = Depends(get_db)):
    result = crud.delete_person(db, person_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Person not found")
    if result == "in_use":
        raise HTTPException(
            status_code=409, detail="Person is still tagged on recurring items or transactions"
        )
    return {"ok": True}
