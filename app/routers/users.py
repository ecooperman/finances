"""The Users page: an administrator lets people in, removes them, and deletes a removed person's data.

Only administrators may use any of this (and only administrators can invite: an ordinary person cannot ask for
anyone to be let in). Everyone's finances stay completely private to them either way: an administrator
cannot read another person's finances through this app, only manage who has an account."""
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from shared_python import accounts_gate, directory
from shared_python.accounts_gate import Account
from sqlalchemy.orm import Session

from .. import config, crud, models, notify, schemas
from ..deps import get_db

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(accounts_gate.require_admin)])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _out(user: models.User) -> schemas.UserOut:
    return schemas.UserOut(id=user.id, email=user.email, status=user.status, is_admin=user.email in config.ADMIN_EMAILS)


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    return [_out(u) for u in crud.list_users(db)]


@router.get("/suggestions", response_model=list[str])
def suggestions(db: Session = Depends(get_db)):
    """Addresses to suggest in the Add box: everyone with an account in any of the apps, minus people who already have
    access here (shared_python.directory). Administrators only - it says who else uses the apps."""
    have = {u.email.lower() for u in db.query(models.User).filter(models.User.status == models.USER_ACTIVE)}
    return [email for email in directory.known_emails() if email not in have]


@router.post("", response_model=schemas.UserOut)
def add_user(body: schemas.UserAdd, background: BackgroundTasks, db: Session = Depends(get_db), admin: Account = Depends(accounts_gate.require_admin)):
    email = crud.normalize_email(body.email)
    if not _EMAIL.match(email) or email == crud.LEGACY_OWNER_EMAIL:
        raise HTTPException(status_code=400, detail="That doesn't look like an email address")
    user, changed = crud.add_user(db, email)
    if changed:  # a new person, or a removed one restored: tell them (never someone who already had access)
        background.add_task(notify.tell_let_in, user.email, admin.email)
    return _out(user)


def _target(db: Session, user_id: int, admin: Account) -> models.User:
    user = crud.get_user(db, user_id)
    if user is None or user.email == crud.LEGACY_OWNER_EMAIL:
        raise HTTPException(status_code=404, detail="No such person")
    if user.email in config.ADMIN_EMAILS or user.id == admin.id:
        raise HTTPException(status_code=409, detail="An administrator's access can't be changed here")
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def set_status(user_id: int, body: schemas.UserStatus, db: Session = Depends(get_db), admin: Account = Depends(accounts_gate.require_admin)):
    return _out(crud.set_user_status(db, _target(db, user_id, admin), body.status))


@router.delete("/{user_id}/data")
def delete_data(user_id: int, db: Session = Depends(get_db), admin: Account = Depends(accounts_gate.require_admin)):
    """Permanently delete everything a REMOVED person owns (their access stays removed)."""
    user = _target(db, user_id, admin)
    if user.status != models.USER_REMOVED:
        raise HTTPException(status_code=409, detail="Remove their access first")
    return {"deleted": crud.delete_user_data(db, user.id)}
