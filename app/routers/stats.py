"""What the dashboard's stats pages ask this app: for each account, when they were last here and how many things they keep in it, as
numbers and dates only (never an amount, a name or a note: this is the household budget). Administrators only. The counts run inside
`owned.unscoped()` because every table here is private to its owner: this is the one place everyone's rows are counted together."""
from fastapi import APIRouter, Depends
from shared_python import accounts_gate, owned, usage
from sqlalchemy.orm import Session

from .. import models
from ..deps import get_db

router = APIRouter(prefix="/api/admin/stats", tags=["stats"], dependencies=[Depends(accounts_gate.require_admin)])


@router.get("")
def stats(db: Session = Depends(get_db)):
    with owned.unscoped():
        return usage.build(db, models.User, {
            "transactions": usage.per_user(db, models.Transaction.owner_id, models.Transaction.created_at),
            "recurring items": usage.per_user(db, models.RecurringItem.owner_id, models.RecurringItem.created_at),
            "sinking funds": usage.per_user(db, models.SinkingFund.owner_id, models.SinkingFund.created_at),
            "scenarios": usage.per_user(db, models.Scenario.owner_id, models.Scenario.created_at),
            "categories": usage.per_user(db, models.Category.owner_id),
        })
