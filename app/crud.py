from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas
from .services import deferrals

# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


def get_people(db: Session):
    return db.query(models.Person).order_by(models.Person.name).all()


def get_person(db: Session, person_id: int):
    return db.query(models.Person).filter(models.Person.id == person_id).first()


def create_person(db: Session, person: schemas.PersonCreate):
    db_person = models.Person(**person.model_dump())
    db.add(db_person)
    db.commit()
    db.refresh(db_person)
    return db_person


def update_person(db: Session, person_id: int, updates: schemas.PersonUpdate):
    db_person = get_person(db, person_id)
    if db_person is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_person, field, value)
    db.commit()
    db.refresh(db_person)
    return db_person


def delete_person(db: Session, person_id: int) -> str:
    db_person = get_person(db, person_id)
    if db_person is None:
        return "not_found"
    in_use = (
        db.query(models.RecurringItem).filter(models.RecurringItem.person_id == person_id).count()
        + db.query(models.Transaction).filter(models.Transaction.person_id == person_id).count()
    )
    if in_use > 0:
        return "in_use"
    db.delete(db_person)
    db.commit()
    return "deleted"


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def get_categories(db: Session):
    return db.query(models.Category).order_by(models.Category.sort_order, models.Category.id).all()


def get_category(db: Session, category_id: int):
    return db.query(models.Category).filter(models.Category.id == category_id).first()


def create_category(db: Session, category: schemas.CategoryCreate):
    max_order = db.query(func.max(models.Category.sort_order)).scalar() or 0
    db_category = models.Category(**category.model_dump(), sort_order=max_order + 10)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


def reorder_categories(db: Session, ordered_ids: List[int]):
    db_categories = db.query(models.Category).filter(models.Category.id.in_(ordered_ids)).all()
    by_id = {c.id: c for c in db_categories}
    for index, category_id in enumerate(ordered_ids):
        db_category = by_id.get(category_id)
        if db_category is None:
            continue
        db_category.sort_order = (index + 1) * 10
    db.commit()
    return get_categories(db)


def update_category(db: Session, category_id: int, updates: schemas.CategoryUpdate):
    db_category = get_category(db, category_id)
    if db_category is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_category, field, value)
    db.commit()
    db.refresh(db_category)
    return db_category


def delete_category(db: Session, category_id: int) -> str:
    db_category = get_category(db, category_id)
    if db_category is None:
        return "not_found"
    in_use = (
        db.query(models.RecurringItem).filter(models.RecurringItem.category_id == category_id).count()
        + db.query(models.Transaction).filter(models.Transaction.category_id == category_id).count()
    )
    if in_use > 0:
        return "in_use"
    db.delete(db_category)
    db.commit()
    return "deleted"


# ---------------------------------------------------------------------------
# Recurring items
# ---------------------------------------------------------------------------


def get_recurring_items(
    db: Session,
    person_id: Optional[int] = None,
    category_id: Optional[int] = None,
    active: Optional[bool] = None,
):
    q = db.query(models.RecurringItem)
    if person_id is not None:
        q = q.filter(models.RecurringItem.person_id == person_id)
    if category_id is not None:
        q = q.filter(models.RecurringItem.category_id == category_id)
    if active is not None:
        q = q.filter(models.RecurringItem.active == active)
    return q.order_by(
        models.RecurringItem.direction,
        models.RecurringItem.day_of_month.is_(None),
        models.RecurringItem.day_of_month,
        models.RecurringItem.name,
    ).all()


def get_recurring_item(db: Session, item_id: int):
    return db.query(models.RecurringItem).filter(models.RecurringItem.id == item_id).first()


def recurring_reference_id_conflict(db: Session, reference_id, exclude_id=None):
    """The other recurring item already using this reference_id, or None."""
    if not reference_id:
        return None
    q = db.query(models.RecurringItem).filter(models.RecurringItem.reference_id == reference_id)
    if exclude_id is not None:
        q = q.filter(models.RecurringItem.id != exclude_id)
    return q.first()


def create_recurring_item(db: Session, item: schemas.RecurringItemCreate):
    db_item = models.RecurringItem(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_recurring_item(db: Session, item_id: int, updates: schemas.RecurringItemUpdate):
    db_item = get_recurring_item(db, item_id)
    if db_item is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_item, field, value)
    if db_item.spread_daily and (db_item.frequency != "monthly" or db_item.direction != "out"):
        db.rollback()
        raise ValueError("only monthly money-out items can be spread across every day")
    db.commit()
    db.refresh(db_item)
    return db_item


def delete_recurring_item(db: Session, item_id: int) -> bool:
    db_item = get_recurring_item(db, item_id)
    if db_item is None:
        return False
    deferrals.clear_for(db, recurring_item_id=item_id)
    db.query(models.DailySpend).filter_by(recurring_item_id=item_id).delete()
    db.delete(db_item)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def get_transactions(
    db: Session,
    date_from=None,
    date_to=None,
    person_id: Optional[int] = None,
    category_id: Optional[int] = None,
):
    q = db.query(models.Transaction)
    if date_from is not None:
        q = q.filter(models.Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(models.Transaction.date <= date_to)
    if person_id is not None:
        q = q.filter(models.Transaction.person_id == person_id)
    if category_id is not None:
        q = q.filter(models.Transaction.category_id == category_id)
    return q.order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).all()


def get_transaction(db: Session, txn_id: int):
    return db.query(models.Transaction).filter(models.Transaction.id == txn_id).first()


def create_transaction(db: Session, txn: schemas.TransactionCreate):
    db_txn = models.Transaction(**txn.model_dump())
    db.add(db_txn)
    db.commit()
    db.refresh(db_txn)
    return db_txn


def update_transaction(db: Session, txn_id: int, updates: schemas.TransactionUpdate):
    db_txn = get_transaction(db, txn_id)
    if db_txn is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_txn, field, value)
    db.commit()
    db.refresh(db_txn)
    return db_txn


def delete_transaction(db: Session, txn_id: int) -> bool:
    db_txn = get_transaction(db, txn_id)
    if db_txn is None:
        return False
    deferrals.clear_for(db, transaction_id=txn_id)
    db.delete(db_txn)
    db.commit()
    return True


def convert_transaction_to_recurring(db: Session, txn_id: int, opts: schemas.ConvertToRecurring):
    """Replace a one-off transaction with an equivalent recurring rule
    (shared fields carried over; the transaction is deleted). Atomic - one
    commit."""
    txn = get_transaction(db, txn_id)
    if txn is None:
        return None
    item = models.RecurringItem(
        name=txn.description,
        amount_cents=txn.amount_cents,
        direction=txn.direction,
        frequency=opts.frequency,
        anchor_month=opts.anchor_month,
        day_of_month=opts.day_of_month if opts.day_of_month is not None else txn.date.day,
        category_id=txn.category_id,
        person_id=txn.person_id,
        start_month=opts.start_month,
        end_month=opts.end_month,
        notes=txn.notes,
        active=True,
    )
    db.add(item)
    deferrals.clear_for(db, transaction_id=txn.id)
    db.delete(txn)
    db.commit()
    db.refresh(item)
    return item


def convert_recurring_to_transaction(db: Session, item_id: int, when):
    """Replace a recurring rule with a single dated transaction on `when`
    (shared fields carried over; the rule is deleted). Atomic."""
    item = get_recurring_item(db, item_id)
    if item is None:
        return None
    txn = models.Transaction(
        date=when,
        description=item.name,
        amount_cents=item.amount_cents,
        direction=item.direction,
        category_id=item.category_id,
        person_id=item.person_id,
        notes=item.notes,
    )
    db.add(txn)
    deferrals.clear_for(db, recurring_item_id=item.id)
    db.query(models.DailySpend).filter_by(recurring_item_id=item.id).delete()
    db.delete(item)
    db.commit()
    db.refresh(txn)
    return txn


# ---------------------------------------------------------------------------
# Sinking funds
# ---------------------------------------------------------------------------


def get_funds(
    db: Session,
    person_id: Optional[int] = None,
    category_id: Optional[int] = None,
    active: Optional[bool] = None,
):
    q = db.query(models.SinkingFund)
    if person_id is not None:
        q = q.filter(models.SinkingFund.person_id == person_id)
    if category_id is not None:
        q = q.filter(models.SinkingFund.category_id == category_id)
    if active is not None:
        q = q.filter(models.SinkingFund.active == active)
    return q.order_by(models.SinkingFund.name).all()


def get_fund(db: Session, fund_id: int):
    return db.query(models.SinkingFund).filter(models.SinkingFund.id == fund_id).first()


def create_fund(db: Session, fund: schemas.FundCreate, default_start_month: str):
    data = fund.model_dump()
    if not data.get("start_month"):
        data["start_month"] = default_start_month
    db_fund = models.SinkingFund(**data)
    db.add(db_fund)
    db.commit()
    db.refresh(db_fund)
    return db_fund


def update_fund(db: Session, fund_id: int, updates: schemas.FundUpdate):
    db_fund = get_fund(db, fund_id)
    if db_fund is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_fund, field, value)
    db.commit()
    db.refresh(db_fund)
    return db_fund


def delete_fund(db: Session, fund_id: int) -> bool:
    db_fund = get_fund(db, fund_id)
    if db_fund is None:
        return False
    db.delete(db_fund)  # tagged transactions' fund_id -> NULL via FK
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Trip settlements (finances' per-trip state; cost is read live elsewhere)
# ---------------------------------------------------------------------------


def get_settlement(db: Session, trip_id: int):
    return (
        db.query(models.TripSettlement)
        .filter(models.TripSettlement.trip_id == trip_id)
        .first()
    )


def get_or_create_settlement(db: Session, trip_id: int) -> models.TripSettlement:
    s = get_settlement(db, trip_id)
    if s is None:
        s = models.TripSettlement(trip_id=trip_id)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def update_settlement(db: Session, trip_id: int, updates: schemas.TripSettlementUpdate):
    s = get_or_create_settlement(db, trip_id)
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    return s


def settle_trip(db: Session, trip_id: int, when, amount_cents: int, name: str,
                travel_category_id):
    """Mark a trip fully paid: create one cash-flow transaction for the
    total and stamp the settlement. The trip then drops out of the forecast.
    """
    s = get_or_create_settlement(db, trip_id)
    if s.settled_at is not None:
        return s  # already settled - no-op
    txn = models.Transaction(
        date=when,
        description=f"{name} (trip)",
        amount_cents=amount_cents,
        direction="out",
        category_id=travel_category_id,
    )
    db.add(txn)
    db.flush()
    s.settled_at = datetime.utcnow()
    s.settled_transaction_id = txn.id
    db.commit()
    db.refresh(s)
    return s


def unsettle_trip(db: Session, trip_id: int):
    s = get_settlement(db, trip_id)
    if s is None or s.settled_at is None:
        return s
    if s.settled_transaction_id is not None:
        txn = get_transaction(db, s.settled_transaction_id)
        if txn is not None:
            deferrals.clear_for(db, transaction_id=txn.id)
            db.delete(txn)
    s.settled_at = None
    s.settled_transaction_id = None
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Scenarios + adjustments
# ---------------------------------------------------------------------------


def get_scenarios(db: Session):
    return db.query(models.Scenario).order_by(models.Scenario.name).all()


def get_scenario(db: Session, scenario_id: int):
    return db.query(models.Scenario).filter(models.Scenario.id == scenario_id).first()


def create_scenario(db: Session, scenario: schemas.ScenarioCreate):
    db_scenario = models.Scenario(**scenario.model_dump())
    db.add(db_scenario)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


def update_scenario(db: Session, scenario_id: int, updates: schemas.ScenarioUpdate):
    db_scenario = get_scenario(db, scenario_id)
    if db_scenario is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_scenario, field, value)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


def delete_scenario(db: Session, scenario_id: int) -> bool:
    db_scenario = get_scenario(db, scenario_id)
    if db_scenario is None:
        return False
    db.delete(db_scenario)
    db.commit()
    return True


def get_adjustment(db: Session, adjustment_id: int):
    return (
        db.query(models.ScenarioAdjustment)
        .filter(models.ScenarioAdjustment.id == adjustment_id)
        .first()
    )


def add_adjustment(db: Session, scenario_id: int, adj: schemas.ScenarioAdjustmentCreate):
    db_adj = models.ScenarioAdjustment(scenario_id=scenario_id, **adj.model_dump())
    db.add(db_adj)
    db.commit()
    db.refresh(db_adj)
    return db_adj


def update_adjustment(db: Session, adjustment_id: int, adj: schemas.ScenarioAdjustmentUpdate):
    db_adj = get_adjustment(db, adjustment_id)
    if db_adj is None:
        return None
    # Full-body replace - clear every non-identity column first so switching
    # an adjustment's `kind` doesn't leave stale fields from the old shape.
    payload = adj.model_dump()
    for field in (
        "kind", "add_kind", "name", "amount_cents", "direction", "frequency", "anchor_month",
        "category_id", "person_id", "target_recurring_id", "target_fund_id", "multiplier",
        "override_amount_cents", "notes",
    ):
        setattr(db_adj, field, payload.get(field))
    db.commit()
    db.refresh(db_adj)
    return db_adj


def delete_adjustment(db: Session, adjustment_id: int) -> bool:
    db_adj = get_adjustment(db, adjustment_id)
    if db_adj is None:
        return False
    db.delete(db_adj)
    db.commit()
    return True
