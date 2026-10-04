"""Daily-spread budget items: a monthly amount as a per-day allowance, with
real costs logged per day against it."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import crud, models, schemas
from app.deps import get_db
from app.main import app
from app.services import deferrals
from app.services.monthly import compute_month
from app.services.paycheck import until_next_paycheck
from app.services.schedule import daily_amounts


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _item(db, **kw):
    kw.setdefault("direction", "out")
    kw.setdefault("frequency", "monthly")
    kw.setdefault("active", True)
    item = models.RecurringItem(**kw)
    db.add(item)
    db.commit()
    return item


def _spend(db, item, day, cents, note=None, month=(2026, 10)):
    db.add(models.DailySpend(recurring_item_id=item.id, date=date(*month, day),
                             amount_cents=cents, note=note))
    db.commit()


def _row(res, name):
    return next(r for r in res.money_out if r.name == name)


def test_daily_amounts_add_up_exactly():
    parts = daily_amounts(30_000, 31)
    assert len(parts) == 31 and sum(parts) == 30_000
    assert max(parts) - min(parts) <= 1
    assert daily_amounts(31_000, 31) == [1_000] * 31


def test_only_monthly_money_out_can_be_spread():
    ok = dict(name="Ubers", amount_cents=30_000, direction="out")
    assert schemas.RecurringItemCreate(**ok, spread_daily=True).spread_daily is True
    with pytest.raises(Exception):
        schemas.RecurringItemCreate(**ok, frequency="weekly", spread_daily=True)
    with pytest.raises(Exception):
        schemas.RecurringItemCreate(name="Pay", amount_cents=1, direction="in", spread_daily=True)


def test_an_unlogged_month_equals_the_budget_and_spreads_over_every_day(db):
    _item(db, name="Ubers", amount_cents=30_000, spread_daily=True, day_of_month=15)
    res = compute_month(db, "2026-10")
    row = _row(res, "Ubers")
    assert row.amount_cents == 30_000 and res.totals.out_cents == 30_000
    assert len(row.daily) == 31 and sum(d.allowance_cents for d in row.daily) == 30_000
    assert row.day is None  # not pinned to its day_of_month any more
    assert res.normalized.out_cents == 30_000


def test_logged_days_replace_the_allowance_and_sum_multiple_entries(db):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)  # $10/day in Oct
    _spend(db, ubers, 3, 1_800, "airport")
    _spend(db, ubers, 3, 2_200, "home")
    _spend(db, ubers, 4, 500)
    res = compute_month(db, "2026-10")
    row = _row(res, "Ubers")
    d3, d4, d5 = row.daily[2], row.daily[3], row.daily[4]
    assert (d3.spent_cents, [e.note for e in d3.entries]) == (4_000, ["airport", "home"])
    assert (d4.spent_cents, d5.entries) == (500, [])
    # Oct 3 counts $40 (not $10), Oct 4 counts $5, the other 29 days $10 each
    assert row.amount_cents == 4_000 + 500 + 29 * 1_000
    assert res.totals.out_cents == row.amount_cents
    assert res.normalized.out_cents == 31_000  # provisioning stays the plan


def test_logging_in_another_month_does_not_leak(db):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    _spend(db, ubers, 3, 9_999, month=(2026, 9))
    assert _row(compute_month(db, "2026-10"), "Ubers").amount_cents == 31_000


def test_a_scenario_rescales_the_plan_but_keeps_real_costs(db):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    _spend(db, ubers, 3, 4_000)
    sc = models.Scenario(name="Fewer ubers")
    db.add(sc)
    db.commit()
    db.add(models.ScenarioAdjustment(scenario_id=sc.id, kind="modify",
                                     target_recurring_id=ubers.id, multiplier=0.5))
    db.commit()
    res = compute_month(db, "2026-10", scenario_id=sc.id)
    row = next(r for r in res.scenario.money_out if r.name == "Ubers")
    assert row.daily[0].allowance_cents == 500
    assert row.daily[2].spent_cents == 4_000
    assert row.amount_cents == 4_000 + 30 * 500


def test_cannot_carry_over_a_daily_item(db):
    ubers = _item(db, name="Ubers", amount_cents=30_000, spread_daily=True)
    with pytest.raises(deferrals.DeferralError):
        deferrals.defer_payment(db, ubers.id, "2026-10")


def test_paycheck_lookahead_counts_the_daily_allowance_to_payday(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=7)
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)  # $10/day
    _spend(db, ubers, 3, 4_000)  # today, already spent $40 (over the $10)
    _spend(db, ubers, 5, 2_500)  # pre-logged future day
    res = until_next_paycheck(db, date(2026, 10, 3))
    # Oct 3 contributes max(10-40, 0) = 0; Oct 4 $10; Oct 5 $25; Oct 6 $10;
    # payday Oct 7's allowance is reported separately.
    assert [(e["name"], e["amount_cents"]) for e in res["before"]] == [
        ("Ubers (daily, 3 days)", 1_000 + 2_500 + 1_000)
    ]
    assert res["before_total_cents"] == 4_500
    assert [(e["name"], e["amount_cents"]) for e in res["on_payday"]] == [("Ubers", 1_000)]


def test_paycheck_today_counts_what_is_left_of_todays_allowance(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=7)
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    _spend(db, ubers, 3, 400)
    res = until_next_paycheck(db, date(2026, 10, 3))
    assert res["before"][0]["amount_cents"] == 600 + 3 * 1_000  # Oct 3 left $6 + Oct 4,5,6


# --- the API ---------------------------------------------------------------


def test_api_log_edit_delete_and_multiple_entries_per_day(db, client):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    plain = _item(db, name="Rent", amount_cents=100_000, day_of_month=1)
    body = {"recurring_item_id": ubers.id, "date": "2026-10-03", "amount_cents": 1_800, "note": "  airport "}
    a = client.post("/api/daily-spend", json=body)
    assert a.status_code == 201 and a.json()["note"] == "airport"
    b = client.post("/api/daily-spend", json={**body, "amount_cents": 2_200, "note": ""})
    assert b.status_code == 201 and b.json()["note"] is None
    row = _row(compute_month(db, "2026-10"), "Ubers")
    assert row.daily[2].spent_cents == 4_000 and len(row.daily[2].entries) == 2

    assert client.patch(f"/api/daily-spend/{b.json()['id']}", json={"amount_cents": 1_000}).json()["amount_cents"] == 1_000
    assert client.delete(f"/api/daily-spend/{a.json()['id']}").status_code == 204
    assert client.delete(f"/api/daily-spend/{a.json()['id']}").status_code == 404

    assert client.post("/api/daily-spend", json={**body, "recurring_item_id": plain.id}).status_code == 400
    assert client.post("/api/daily-spend", json={**body, "recurring_item_id": 999}).status_code == 404
    assert client.post("/api/daily-spend", json={**body, "amount_cents": 0}).status_code == 422


def test_api_patch_rejects_an_invalid_spread(db, client):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    r = client.patch(f"/api/recurring/{ubers.id}", json={"frequency": "weekly"})
    assert r.status_code == 422
    assert client.patch(f"/api/recurring/{ubers.id}", json={"spread_daily": False}).status_code == 200


def test_daily_budget_standing(db, client):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)  # $10/day
    _item(db, name="Rent", amount_cents=100_000, day_of_month=1)
    _spend(db, ubers, 1, 1_500)  # +$5 over
    _spend(db, ubers, 3, 400)    # -$6 under (today)
    res = client.get("/api/daily-budget", params={"on": "2026-10-03"}).json()
    [it] = res["items"]
    assert it["name"] == "Ubers" and it["allowance_cents"] == 1_000
    assert it["spent_today_cents"] == 400 and it["left_today_cents"] == 600
    assert it["logged_over_under_cents"] == 500 - 600
    # through Oct 3: $15 + $10 (Oct 2 assumed) + $4 = $29 effective
    assert it["month_left_cents"] == 31_000 - 2_900
    assert it["days_left"] == 28 and it["per_day_left_cents"] == (31_000 - 2_900) // 28
    assert [e["amount_cents"] for e in it["entries_today"]] == [400]


def test_deleting_the_item_clears_its_logged_costs(db):
    ubers = _item(db, name="Ubers", amount_cents=31_000, spread_daily=True)
    _spend(db, ubers, 3, 400)
    crud.delete_recurring_item(db, ubers.id)
    assert db.query(models.DailySpend).count() == 0
