from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas

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
    db.commit()
    db.refresh(db_item)
    return db_item


def delete_recurring_item(db: Session, item_id: int) -> bool:
    db_item = get_recurring_item(db, item_id)
    if db_item is None:
        return False
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
    db.delete(db_txn)
    db.commit()
    return True


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
        "kind", "name", "amount_cents", "direction", "frequency", "anchor_month",
        "category_id", "person_id", "target_recurring_id", "multiplier",
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
