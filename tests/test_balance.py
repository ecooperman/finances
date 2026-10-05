"""A month's closing balance rolls into the next month's opening, with a
manual override for when the logged expenses don't match the real balance."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import models
from app.deps import get_db
from app.main import app
from app.services import balance
from app.services.monthly import compute_month


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def chain_from_oct(db):
    db.add(models.AppSetting(key=balance.START_KEY, value="2026-10"))
    db.commit()


def _item(db, **kw):
    kw.setdefault("direction", "out")
    kw.setdefault("frequency", "monthly")
    kw.setdefault("active", True)
    item = models.RecurringItem(**kw)
    db.add(item)
    db.commit()
    return item


def test_a_months_closing_balance_opens_the_next_month(db, chain_from_oct):
    # Evan's October: three Fridays of pay, then Nov 1 bills.
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", frequency="biweekly",
          day_of_week=5, week_anchor=date(2026, 10, 2))            # Oct 2, 16, 30; Nov 13, 27
    _item(db, name="Rent", amount_cents=250_000, day_of_month=1)
    oct_ = compute_month(db, "2026-10").opening
    assert (oct_.opening_cents, oct_.from_month) == (0, None)       # start of the chain
    assert oct_.closing_cents == 3 * 600_000 - 250_000
    nov = compute_month(db, "2026-11").opening
    assert (nov.opening_cents, nov.from_month) == (oct_.closing_cents, "2026-10")
    assert nov.override_cents is None
    # Nov 1 rent no longer drives the running balance negative: it starts at +15,500
    assert nov.closing_cents == oct_.closing_cents + 2 * 600_000 - 250_000


def test_a_manual_override_replaces_the_rollover_and_later_months_follow_it(db, chain_from_oct):
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5)
    _item(db, name="Bills", amount_cents=40_000, day_of_month=10)
    balance.set_override(db, "2026-11", 500_000, "matched to the bank")
    nov = compute_month(db, "2026-11").opening
    assert (nov.computed_cents, nov.override_cents, nov.opening_cents) == (60_000, 500_000, 500_000)
    assert nov.note == "matched to the bank"
    dec = compute_month(db, "2026-12").opening
    assert dec.opening_cents == 500_000 + 60_000       # rolls from the override
    assert dec.from_month == "2026-11"


def test_a_negative_override_is_allowed_and_can_be_cleared(db, chain_from_oct):
    balance.set_override(db, "2026-10", -12_345, None)
    assert compute_month(db, "2026-10").opening.opening_cents == -12_345
    assert balance.clear_override(db, "2026-10") is True
    assert compute_month(db, "2026-10").opening.opening_cents == 0
    assert balance.clear_override(db, "2026-10") is False


def test_items_with_no_set_day_are_not_in_the_rollover(db, chain_from_oct):
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5)
    _item(db, name="Electric", amount_cents=30_000)          # monthly, no day
    assert compute_month(db, "2026-10").opening.closing_cents == 100_000


def test_daily_and_carried_over_items_roll_like_the_calendar(db, chain_from_oct):
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5)
    _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    assert compute_month(db, "2026-10").opening.closing_cents == 100_000 - 31_000


def test_before_the_chain_starts_nothing_rolls(db, chain_from_oct):
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5)
    sep = compute_month(db, "2026-09").opening
    assert (sep.opening_cents, sep.from_month) == (0, None)
    assert compute_month(db, "2026-10").opening.opening_cents == 0   # Sep doesn't roll in


def test_an_earlier_override_moves_the_start_of_the_chain(db, chain_from_oct):
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5)
    balance.set_override(db, "2026-09", 20_000, None)
    assert compute_month(db, "2026-10").opening.opening_cents == 120_000


def test_the_balance_ignores_filters_and_scenarios(db, chain_from_oct):
    p = models.Person(name="Rach", color="#111")
    db.add(p)
    db.commit()
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5, person_id=p.id)
    unfiltered = compute_month(db, "2026-11").opening.opening_cents
    assert compute_month(db, "2026-11", person_id=p.id + 1).opening.opening_cents == unfiltered == 100_000


def test_start_month_is_created_lazily_when_missing(db):
    assert db.get(models.AppSetting, balance.START_KEY) is None
    compute_month(db, "2026-10")
    assert db.get(models.AppSetting, balance.START_KEY).value == date.today().strftime("%Y-%m")


def test_api_set_and_clear(db, client, chain_from_oct):
    _item(db, name="Pay", amount_cents=100_000, direction="in", day_of_month=5)
    r = client.put("/api/opening-balance/2026-11", json={"amount_cents": 250_000, "note": " bank "})
    assert r.status_code == 200
    assert (r.json()["opening_cents"], r.json()["override_cents"], r.json()["note"]) == (250_000, 250_000, "bank")
    assert client.get("/api/monthly", params={"month": "2026-11"}).json()["opening"]["opening_cents"] == 250_000
    assert client.put("/api/opening-balance/2026-11", json={"amount_cents": 1}).json()["override_cents"] == 1  # upsert
    r = client.delete("/api/opening-balance/2026-11")
    assert r.status_code == 200 and r.json()["override_cents"] is None and r.json()["opening_cents"] == 100_000
    assert client.delete("/api/opening-balance/2026-11").status_code == 404
    assert client.put("/api/opening-balance/2026-13", json={"amount_cents": 1}).status_code == 422


# --- the balance on the "until next paycheck" lookahead -------------------

from app.services.paycheck import until_next_paycheck  # noqa: E402


def _pay_setup(db):
    balance.set_override(db, "2026-10", 100_000, None)             # real balance on Oct 1
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", frequency="biweekly",
          day_of_week=5, week_anchor=date(2026, 10, 2))             # Oct 2, 16, 30
    _item(db, name="Rent", amount_cents=250_000, day_of_month=1)
    _item(db, name="Loan A", amount_cents=10_000, day_of_month=6)   # before payday
    _item(db, name="Loan B", amount_cents=30_000, day_of_month=16)  # on payday


def test_the_lookahead_shows_the_balance_now_before_and_after_payday(db, chain_from_oct):
    _pay_setup(db)
    res = until_next_paycheck(db, date(2026, 10, 4))                # next paycheck Oct 16
    # 1,000 opening + Oct 2 pay 6,000 - Oct 1 rent 2,500
    assert res["balance_now_cents"] == 100_000 + 600_000 - 250_000
    assert res["before_total_cents"] == 10_000
    assert res["balance_before_payday_cents"] == 450_000 - 10_000
    assert res["balance_after_payday_cents"] == 440_000 + 600_000 - 30_000


def test_a_paycheck_landing_today_is_in_the_balance_but_todays_bills_are_not(db, chain_from_oct):
    _pay_setup(db)
    _item(db, name="Today loan", amount_cents=20_000, day_of_month=2)
    res = until_next_paycheck(db, date(2026, 10, 2))
    assert res["balance_now_cents"] == 100_000 + 600_000 - 250_000   # pay received, loan still ahead
    assert [e["name"] for e in res["before"]] == ["Today loan", "Loan A"]
    assert res["balance_before_payday_cents"] == 450_000 - 20_000 - 10_000


def test_other_income_before_payday_raises_the_balance_before_it(db, chain_from_oct):
    _pay_setup(db)
    p = models.Person(name="Rach", color="#111")
    db.add(p)
    db.commit()
    evan = models.Person(name="Evan", color="#222")
    db.add(evan)
    db.commit()
    db.query(models.RecurringItem).filter_by(name="Paycheck").update({"person_id": evan.id})
    _item(db, name="Rach pay", amount_cents=400_000, direction="in", day_of_month=9, person_id=p.id)
    db.commit()
    res = until_next_paycheck(db, date(2026, 10, 4), person_id=evan.id)  # Evan's pay is Oct 16
    assert res["next_paycheck"]["name"] == "Paycheck" and res["next_paycheck"]["date"] == date(2026, 10, 16)
    assert res["income_before_cents"] == 400_000
    assert res["balance_before_payday_cents"] == 450_000 + 400_000 - 10_000


def test_daily_spending_already_logged_today_leaves_the_balance(db, chain_from_oct):
    _pay_setup(db)
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)   # $10/day
    db.add(models.DailySpend(recurring_item_id=ubers.id, date=date(2026, 10, 4), amount_cents=4_000))
    db.commit()
    res = until_next_paycheck(db, date(2026, 10, 4))
    # Oct 1-3 at the $10 allowance are behind us, today's logged $40 is spent
    assert res["balance_now_cents"] == 450_000 - 3 * 1_000 - 4_000
    # nothing is left of today's allowance; Oct 5-15 are still ahead (11 days x $10)
    ubers_line = next(e for e in res["before"] if e["name"].startswith("Ubers"))
    assert (ubers_line["name"], ubers_line["amount_cents"]) == ("Ubers (daily, 11 days)", 11_000)
    assert res["balance_before_payday_cents"] == res["balance_now_cents"] - res["before_total_cents"]


def test_no_paycheck_still_reports_the_balance_now(db, chain_from_oct):
    _item(db, name="Rent", amount_cents=250_000, day_of_month=1)
    res = until_next_paycheck(db, date(2026, 10, 4))
    assert res["next_paycheck"] is None
    assert res["balance_now_cents"] == -250_000
    assert res["balance_before_payday_cents"] is None
