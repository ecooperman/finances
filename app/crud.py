from datetime import datetime
from typing import List, Optional

from shared_python import owned
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas
from .seed import seed_categories
from .services import deferrals


class BadReference(Exception):
    """A request named a category, person, fund... that is not the caller's (or does not exist). Answered with a 400: nothing
    says WHICH of the two it is, so ids cannot be used to find out what another person has."""


# The ids a request can name, and what to call each in the message. Each must be one of the caller's own rows: the data
# layer only ever finds the caller's rows (shared_python.owned), and shared_python.owned also refuses to save a row that
# points at someone else's, so this is the friendly front of two backstops.
_REFERENCES = {
    "category_id": (models.Category, "category"),
    "person_id": (models.Person, "person"),
    "fund_id": (models.SinkingFund, "fund"),
    "target_recurring_id": (models.RecurringItem, "recurring item"),
    "target_fund_id": (models.SinkingFund, "fund"),
    "target_transaction_id": (models.Transaction, "transaction"),
}


def check_references(db: Session, data: dict) -> None:
    """Raise BadReference if `data` names an id that is not one of the caller's own rows."""
    for field, (model, what) in _REFERENCES.items():
        value = data.get(field)
        if value is not None and db.query(model.id).filter(model.id == value).first() is None:
            raise BadReference(f"That {what} doesn't exist")

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
    check_references(db, item.model_dump())
    db_item = models.RecurringItem(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_recurring_item(db: Session, item_id: int, updates: schemas.RecurringItemUpdate):
    db_item = get_recurring_item(db, item_id)
    if db_item is None:
        return None
    check_references(db, updates.model_dump(exclude_unset=True))
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
    check_references(db, txn.model_dump())
    db_txn = models.Transaction(**txn.model_dump())
    db.add(db_txn)
    db.commit()
    db.refresh(db_txn)
    return db_txn


def update_transaction(db: Session, txn_id: int, updates: schemas.TransactionUpdate):
    db_txn = get_transaction(db, txn_id)
    if db_txn is None:
        return None
    check_references(db, updates.model_dump(exclude_unset=True))
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_txn, field, value)
    db.commit()
    db.refresh(db_txn)
    return db_txn


def _clear_transaction_refs(db: Session, txn_id: int) -> None:
    """A transaction is going away: drop what points at it (carry-overs and
    scenario changes that target it). SQLite isn't enforcing FK cascades, so
    this is done by hand. Doesn't commit."""
    deferrals.clear_for(db, transaction_id=txn_id)
    db.query(models.ScenarioAdjustment).filter_by(target_transaction_id=txn_id).delete()


def delete_transaction(db: Session, txn_id: int) -> bool:
    db_txn = get_transaction(db, txn_id)
    if db_txn is None:
        return False
    _clear_transaction_refs(db, txn_id)
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
    _clear_transaction_refs(db, txn.id)
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
    check_references(db, data)
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
    check_references(db, updates.model_dump(exclude_unset=True))
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
            _clear_transaction_refs(db, txn.id)
            db.delete(txn)
    s.settled_at = None
    s.settled_transaction_id = None
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Linked lists (finances' per-list state; the cost is read live from lists)
# ---------------------------------------------------------------------------


def get_linked_list(db: Session, list_id: int):
    return db.query(models.LinkedList).filter(models.LinkedList.list_id == list_id).first()


def link_list(db: Session, list_id: int, name: str, due_date):
    """Link a list into the budget (one link per list; linking again returns the existing one)."""
    link = get_linked_list(db, list_id)
    if link is None:
        link = models.LinkedList(list_id=list_id, name=name, due_date=due_date)
        db.add(link)
        db.commit()
        db.refresh(link)
    return link


def update_linked_list(db: Session, list_id: int, updates: schemas.LinkedListUpdate):
    link = get_linked_list(db, list_id)
    if link is None:
        return None
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(link, field, value)
    db.commit()
    db.refresh(link)
    return link


def unlink_list(db: Session, list_id: int) -> bool:
    """Take a list out of the budget. A settled link keeps its transaction (that spend is real);
    only the link goes."""
    link = get_linked_list(db, list_id)
    if link is None:
        return False
    db.delete(link)
    db.commit()
    return True


def settle_linked_list(db: Session, list_id: int, when, amount_cents: int, name: str):
    """Mark a linked list fully paid: one cash-flow transaction for the amount, and the link stops
    forecasting (same as settling a trip)."""
    link = get_linked_list(db, list_id)
    if link is None:
        return None
    if link.settled_at is not None:
        return link
    txn = models.Transaction(date=when, description=f"{name} (list)", amount_cents=amount_cents, direction="out")
    db.add(txn)
    db.flush()
    link.settled_at = datetime.utcnow()
    link.settled_transaction_id = txn.id
    db.commit()
    db.refresh(link)
    return link


def unsettle_linked_list(db: Session, list_id: int):
    link = get_linked_list(db, list_id)
    if link is None or link.settled_at is None:
        return link
    if link.settled_transaction_id is not None:
        txn = get_transaction(db, link.settled_transaction_id)
        if txn is not None:
            _clear_transaction_refs(db, txn.id)
            db.delete(txn)
    link.settled_at = None
    link.settled_transaction_id = None
    db.commit()
    db.refresh(link)
    return link


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
    check_references(db, adj.model_dump())
    db_adj = models.ScenarioAdjustment(scenario_id=scenario_id, **adj.model_dump())
    db.add(db_adj)
    db.commit()
    db.refresh(db_adj)
    return db_adj


def update_adjustment(db: Session, adjustment_id: int, adj: schemas.ScenarioAdjustmentUpdate):
    db_adj = get_adjustment(db, adjustment_id)
    if db_adj is None:
        return None
    check_references(db, adj.model_dump())
    # Full-body replace - clear every non-identity column first so switching
    # an adjustment's `kind` doesn't leave stale fields from the old shape.
    payload = adj.model_dump()
    for field in (
        "kind", "add_kind", "name", "amount_cents", "direction", "frequency", "anchor_month",
        "date", "category_id", "person_id", "target_recurring_id", "target_fund_id",
        "target_transaction_id", "multiplier", "override_amount_cents", "notes",
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


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
# The users table is not an owned table (it is how ownership is decided), so these are the only queries that run
# without a person in scope, apart from seeding a new account's default categories (inside THEIR scope).

LEGACY_OWNER_EMAIL = "legacy-owner@finances.invalid"


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == normalize_email(email)).first()


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def list_users(db: Session):
    return db.query(models.User).filter(models.User.email != LEGACY_OWNER_EMAIL).order_by(func.lower(models.User.email)).all()


def _seed_new_account(db: Session, user) -> None:
    with owned.scope(user.id):
        seed_categories(db)


def adopt_or_create_admin(db: Session, email: str):
    """An administrator's account, made the first time they sign in. If the data that existed before accounts is
    still parked on the placeholder, they take it over by giving it their email: it all becomes theirs without a
    single row moving."""
    email = normalize_email(email)
    existing = get_user_by_email(db, email)
    if existing is not None:
        return existing
    legacy = db.query(models.User).filter(models.User.email == LEGACY_OWNER_EMAIL).first()
    if legacy is not None:
        legacy.email = email
        user = legacy
        db.commit()
    else:
        user = models.User(email=email)
        db.add(user)
        db.commit()
        _seed_new_account(db, user)
    return user


def add_user(db: Session, email: str):
    """Let someone in (an administrator's decision). Returns (user, changed): a person whose access was removed is
    restored, and someone who already has access is left as they are."""
    email = normalize_email(email)
    user = get_user_by_email(db, email)
    if user is not None:
        restored = user.status != models.USER_ACTIVE
        user.status = models.USER_ACTIVE
        db.commit()
        return user, restored
    user = models.User(email=email)
    db.add(user)
    db.commit()
    _seed_new_account(db, user)
    return user, True


def set_user_status(db: Session, user, status: str):
    user.status = status
    db.commit()
    return user


def delete_user_data(db: Session, user_id: int) -> dict:
    """Permanently delete everything a person owns. Runs inside THEIR scope (never anyone else's), children first."""
    counts = {}
    with owned.scope(user_id):
        for key, model in (
            ("scenario_adjustments", models.ScenarioAdjustment), ("scenarios", models.Scenario),
            ("deferrals", models.PaymentDeferral), ("daily_spend", models.DailySpend),
            ("trip_settlements", models.TripSettlement), ("linked_lists", models.LinkedList),
            ("transactions", models.Transaction), ("recurring_items", models.RecurringItem),
            ("funds", models.SinkingFund), ("opening_balances", models.MonthOpeningBalance),
            ("settings", models.AppSetting), ("categories", models.Category), ("people", models.Person),
        ):
            counts[key] = db.query(model).delete(synchronize_session=False)
        db.commit()
    return counts
