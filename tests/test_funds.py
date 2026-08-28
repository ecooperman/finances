"""Sinking-fund balance math and the provisioning aggregation."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import crud, models, schemas
from app.services.funds import fund_status, funds_summary, months_elapsed
from app.services.monthly import compute_month


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _fund(db, **kw):
    kw.setdefault("name", "Vet")
    kw.setdefault("annual_amount_cents", 120_000)  # $1,200/yr -> $100/mo
    kw.setdefault("start_month", "2026-01")
    kw.setdefault("active", True)
    f = models.SinkingFund(**kw)
    db.add(f)
    db.commit()
    return f


def _spend(db, fund, when, cents, direction="out"):
    db.add(models.Transaction(
        date=when, description="visit", amount_cents=cents, direction=direction, fund_id=fund.id,
    ))
    db.commit()


# --- balance math ----------------------------------------------------


def test_months_elapsed_inclusive_and_floored():
    assert months_elapsed("2026-01", "2026-01") == 1
    assert months_elapsed("2026-01", "2026-06") == 6
    assert months_elapsed("2026-01", "2027-01") == 13
    assert months_elapsed("2026-06", "2026-01") == 0  # as_of before start


def test_accrual_and_balance(db):
    fund = _fund(db)  # $100/mo from 2026-01
    st = fund_status(db, fund, "2026-04")
    assert st["monthly_contribution_cents"] == 10_000
    assert st["accrued_cents"] == 40_000
    assert st["spent_cents"] == 0
    assert st["balance_cents"] == 40_000


def test_spend_draws_balance_down(db):
    fund = _fund(db)
    _spend(db, fund, date(2026, 3, 10), 25_000)
    st = fund_status(db, fund, "2026-04")
    assert st["accrued_cents"] == 40_000
    assert st["spent_cents"] == 25_000
    assert st["balance_cents"] == 15_000


def test_balance_carries_over_year_boundary(db):
    fund = _fund(db)  # $100/mo
    _spend(db, fund, date(2026, 5, 1), 30_000)   # underspent year 1
    # As of 2027-03: 15 months accrued = 150_000; spent 30_000 -> +120_000
    st = fund_status(db, fund, "2027-03")
    assert st["accrued_cents"] == 150_000
    assert st["balance_cents"] == 120_000
    # YTD is scoped to 2027 only -> nothing spent in 2027
    assert st["spent_ytd_cents"] == 0


def test_overspend_goes_negative(db):
    fund = _fund(db)
    _spend(db, fund, date(2026, 2, 1), 90_000)
    st = fund_status(db, fund, "2026-03")  # accrued 30_000
    assert st["balance_cents"] == -60_000


def test_spent_ytd_is_calendar_year_scoped(db):
    fund = _fund(db)
    _spend(db, fund, date(2026, 11, 1), 20_000)
    _spend(db, fund, date(2027, 2, 1), 15_000)
    st = fund_status(db, fund, "2027-06")
    assert st["spent_cents"] == 35_000       # all-time
    assert st["spent_ytd_cents"] == 15_000   # 2027 only


def test_funds_summary_aggregates_active_only(db):
    _fund(db, name="Vet", annual_amount_cents=120_000)          # $100/mo
    _fund(db, name="Grooming", annual_amount_cents=60_000)      # $50/mo
    _fund(db, name="Old", annual_amount_cents=999_999, active=False)
    s = funds_summary(db, "2026-02")
    assert s["active_count"] == 2
    assert s["monthly_total_cents"] == 15_000
    assert s["banked_total_cents"] == 30_000  # 2 months * 15_000, nothing spent


# --- provisioning aggregation (compute_month) ----------------------


def _recurring(db, **kw):
    kw.setdefault("name", "Mortgage")
    kw.setdefault("amount_cents", 300_000)
    kw.setdefault("direction", "out")
    kw.setdefault("frequency", "monthly")
    kw.setdefault("active", True)
    r = models.RecurringItem(**kw)
    db.add(r)
    db.commit()
    return r


def test_normalized_is_recurring_plus_funds_excluding_oneoffs(db):
    _recurring(db, name="Salary", amount_cents=900_000, direction="in")
    _recurring(db, name="Mortgage", amount_cents=300_000, direction="out")
    _fund(db, name="Vet", annual_amount_cents=120_000)  # $100/mo
    db.add(models.Transaction(date=date(2026, 6, 15), description="surprise", amount_cents=50_000, direction="out"))
    db.commit()

    res = compute_month(db, "2026-06")
    # cash flow: includes the one-off
    assert res.totals.out_cents == 300_000 + 50_000
    # provisioning: recurring smoothed + fund, NO one-off
    assert res.normalized.out_cents == 300_000 + 10_000
    assert res.normalized.in_cents == 900_000


def test_fund_tagged_transaction_still_hits_cash_flow(db):
    fund = _fund(db, name="Vet", annual_amount_cents=120_000)
    db.add(models.Transaction(date=date(2026, 6, 3), description="vet", amount_cents=28_000, direction="out", fund_id=fund.id))
    db.commit()
    res = compute_month(db, "2026-06")
    assert res.totals.out_cents == 28_000          # cash flow sees it
    assert res.normalized.out_cents == 10_000      # provisioning: just the set-aside


def _scenario(db, *adjustments):
    s = models.Scenario(name="What if")
    db.add(s)
    db.commit()
    for adj in adjustments:
        db.add(models.ScenarioAdjustment(scenario_id=s.id, **adj))
    db.commit()
    return s


def test_scenario_fund_adjustments_move_provisioning_not_cashflow(db):
    _recurring(db, name="Mortgage", amount_cents=300_000, direction="out")
    grooming = _fund(db, name="Grooming", annual_amount_cents=60_000)  # $50/mo

    scenario = _scenario(
        db,
        dict(kind="add", add_kind="fund", name="Boarding", amount_cents=120_000),  # +$100/mo
        dict(kind="modify", target_fund_id=grooming.id, multiplier=1.5),           # $50 -> $75
    )
    res = compute_month(db, "2026-06", scenario_id=scenario.id)

    # cash flow untouched by fund adjustments
    assert res.scenario.totals.out_cents == res.totals.out_cents == 300_000
    assert res.scenario.delta.net_cents == 0
    # provisioning: mortgage 300k smoothed + grooming 75 + boarding 100
    assert res.normalized.out_cents == 300_000 + 5_000        # baseline: mortgage + $50 grooming
    assert res.scenario.normalized.out_cents == 300_000 + 7_500 + 10_000
    # provisioning delta = +$25 (grooming) + $100 (boarding) = -$125 to net
    assert res.scenario.normalized_delta.net_cents == -(2_500 + 10_000)


def test_scenario_remove_fund(db):
    vet = _fund(db, name="Vet", annual_amount_cents=120_000)  # $100/mo
    scenario = _scenario(db, dict(kind="remove", target_fund_id=vet.id))
    res = compute_month(db, "2026-06", scenario_id=scenario.id)
    assert res.normalized.out_cents == 10_000
    assert res.scenario.normalized.out_cents == 0
