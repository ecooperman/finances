"""Tests for the monthly-view aggregation (app/services/monthly.py) - the
one piece of real logic in the app. Runs against a throwaway in-memory
SQLite DB with the schema built straight from the models (fine for tests;
the real app still owns its schema through Alembic).

    cd finances && source venv/bin/activate && pytest
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import crud, models, schemas
from app.services.monthly import compute_month


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _person(db, name="Evan"):
    p = models.Person(name=name, color="#123456")
    db.add(p)
    db.commit()
    return p


def _cat(db, name="Housing"):
    c = models.Category(name=name, color="#334455", text_color="light", sort_order=10)
    db.add(c)
    db.commit()
    return c


def _recurring(db, **kw):
    kw.setdefault("name", "Item")
    kw.setdefault("amount_cents", 100_00)
    kw.setdefault("direction", "out")
    kw.setdefault("frequency", "monthly")
    kw.setdefault("active", True)
    item = models.RecurringItem(**kw)
    db.add(item)
    db.commit()
    return item


# --- cash-flow math -----------------------------------------------------


def test_net_is_in_minus_out(db):
    _recurring(db, name="Salary", amount_cents=900_000, direction="in")
    _recurring(db, name="Mortgage", amount_cents=320_000, direction="out")
    res = compute_month(db, "2026-09")
    assert res.totals.in_cents == 900_000
    assert res.totals.out_cents == 320_000
    assert res.totals.net_cents == 580_000


def test_transactions_land_in_their_calendar_month(db):
    db.add(models.Transaction(date=date(2026, 9, 15), description="Bonus", amount_cents=50_000, direction="in"))
    db.add(models.Transaction(date=date(2026, 10, 1), description="Next month", amount_cents=1, direction="in"))
    db.commit()
    res = compute_month(db, "2026-09")
    names = [r.name for r in res.money_in]
    assert names == ["Bonus"]
    assert res.totals.in_cents == 50_000


# --- non-monthly cadence ---------------------------------------------


def test_annual_item_only_lands_in_its_anchor_month(db):
    _recurring(db, name="Property tax", amount_cents=600_000, direction="out", frequency="annual", anchor_month=4)

    sept = compute_month(db, "2026-09")
    assert sept.totals.out_cents == 0  # doesn't land
    # but it is smoothed into the normalized figure: 600_000 / 12
    assert sept.normalized.out_cents == 50_000

    april = compute_month(db, "2027-04")
    assert april.totals.out_cents == 600_000
    assert april.normalized.out_cents == 50_000


def test_quarterly_item_lands_every_third_month(db):
    _recurring(db, name="Water", amount_cents=30_000, direction="out", frequency="quarterly", anchor_month=2)
    landed = [m for m in range(1, 13) if compute_month(db, f"2026-{m:02d}").totals.out_cents == 30_000]
    assert landed == [2, 5, 8, 11]


def test_start_and_end_month_bounds(db):
    _recurring(db, name="Car loan", amount_cents=45_000, direction="out", start_month="2026-03", end_month="2026-05")
    assert compute_month(db, "2026-02").totals.out_cents == 0
    assert compute_month(db, "2026-03").totals.out_cents == 45_000
    assert compute_month(db, "2026-05").totals.out_cents == 45_000
    assert compute_month(db, "2026-06").totals.out_cents == 0


def test_inactive_item_is_excluded(db):
    _recurring(db, name="Paused", amount_cents=10_000, direction="out", active=False)
    res = compute_month(db, "2026-09")
    assert res.totals.out_cents == 0


# --- filters -----------------------------------------------------------


def test_person_and_joint_filters(db):
    evan = _person(db, "Evan")
    _recurring(db, name="Evan salary", amount_cents=900_000, direction="in", person_id=evan.id)
    _recurring(db, name="Mortgage", amount_cents=320_000, direction="out", person_id=None)

    only_evan = compute_month(db, "2026-09", person_id=evan.id)
    assert only_evan.totals.in_cents == 900_000
    assert only_evan.totals.out_cents == 0

    joint = compute_month(db, "2026-09", joint_only=True)
    assert joint.totals.in_cents == 0
    assert joint.totals.out_cents == 320_000


def test_category_filter(db):
    housing = _cat(db, "Housing")
    food = _cat(db, "Food")
    _recurring(db, name="Mortgage", amount_cents=320_000, direction="out", category_id=housing.id)
    _recurring(db, name="Groceries", amount_cents=60_000, direction="out", category_id=food.id)

    res = compute_month(db, "2026-09", category_ids=[housing.id])
    assert res.totals.out_cents == 320_000
    assert [r.name for r in res.money_out] == ["Mortgage"]


# --- scenarios -------------------------------------------------------


def _scenario(db, *adjustments):
    s = models.Scenario(name="What if")
    db.add(s)
    db.commit()
    for adj in adjustments:
        db.add(models.ScenarioAdjustment(scenario_id=s.id, **adj))
    db.commit()
    return s


def test_scenario_add_remove_modify(db):
    salary = _recurring(db, name="Salary", amount_cents=900_000, direction="in")
    mortgage = _recurring(db, name="Mortgage", amount_cents=320_000, direction="out")
    uber = _recurring(db, name="Uber", amount_cents=40_000, direction="out")

    scenario = _scenario(
        db,
        dict(kind="add", name="Car payment", amount_cents=45_000, direction="out", frequency="monthly"),
        dict(kind="modify", target_recurring_id=uber.id, multiplier=0.5),
        dict(kind="remove", target_recurring_id=mortgage.id),
    )

    res = compute_month(db, "2026-09", scenario_id=scenario.id)

    # baseline untouched
    assert res.totals.out_cents == 320_000 + 40_000
    assert res.totals.net_cents == 900_000 - 360_000

    scen = res.scenario
    assert scen is not None
    # out = uber halved (20_000) + car payment (45_000); mortgage removed
    assert scen.totals.out_cents == 20_000 + 45_000
    assert scen.totals.net_cents == 900_000 - 65_000
    assert scen.delta.net_cents == scen.totals.net_cents - res.totals.net_cents

    effects = {r.name: r.effect for r in scen.money_out}
    assert effects["Car payment"] == "added"
    assert effects["Uber"] == "modified"
    assert effects["Mortgage"] == "removed"
    # a removed row is shown but not counted
    removed = next(r for r in scen.money_out if r.name == "Mortgage")
    assert removed.effect == "removed"


def test_transaction_update_schema_accepts_a_date(db):
    # Regression: the field named `date` typed as `date` used to rebind the
    # name and leave TransactionUpdate.date accepting only None (422 on any
    # real PATCH).
    parsed = schemas.TransactionUpdate(date="2026-08-28", amount_cents=100)
    assert parsed.date == date(2026, 8, 28)
    assert schemas.TransactionUpdate().date is None


def test_convert_transaction_to_recurring_carries_fields_and_deletes_txn(db):
    cat = _cat(db)
    person = _person(db)
    db.add(models.Transaction(
        date=date(2026, 3, 14), description="Gym membership", amount_cents=5000,
        direction="out", category_id=cat.id, person_id=person.id, notes="annual? no, monthly",
    ))
    db.commit()
    txn_id = db.query(models.Transaction).one().id

    item = crud.convert_transaction_to_recurring(
        db, txn_id, schemas.ConvertToRecurring(frequency="monthly")
    )
    assert item.name == "Gym membership"
    assert item.amount_cents == 5000
    assert item.direction == "out"
    assert item.category_id == cat.id and item.person_id == person.id
    assert item.notes == "annual? no, monthly"
    assert item.day_of_month == 14  # defaulted from the transaction's date
    assert item.active is True
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.RecurringItem).count() == 1


def test_convert_recurring_to_transaction_carries_fields_and_deletes_rule(db):
    item = _recurring(db, name="Old subscription", amount_cents=1200, direction="out")
    txn = crud.convert_recurring_to_transaction(db, item.id, date(2026, 9, 1))
    assert txn.description == "Old subscription"
    assert txn.amount_cents == 1200
    assert txn.date == date(2026, 9, 1)
    assert db.query(models.RecurringItem).count() == 0
    assert db.query(models.Transaction).count() == 1


def test_convert_missing_ids_return_none(db):
    assert crud.convert_transaction_to_recurring(db, 999, schemas.ConvertToRecurring()) is None
    assert crud.convert_recurring_to_transaction(db, 999, date(2026, 1, 1)) is None


def test_scenario_modify_override_amount(db):
    mortgage = _recurring(db, name="Mortgage", amount_cents=320_000, direction="out")
    scenario = _scenario(
        db, dict(kind="modify", target_recurring_id=mortgage.id, override_amount_cents=352_000)
    )
    res = compute_month(db, "2026-09", scenario_id=scenario.id)
    row = next(r for r in res.scenario.money_out if r.name == "Mortgage")
    assert row.amount_cents == 352_000
    assert row.original_amount_cents == 320_000
    assert res.scenario.totals.out_cents == 352_000
