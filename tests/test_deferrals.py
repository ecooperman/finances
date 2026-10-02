"""Payments that couldn't be made this month and carry into the next."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import models
from app.deps import get_db
from app.main import app
from app.services import deferrals as svc
from app.services.monthly import compute_month
from app.services.paycheck import until_next_paycheck


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


def _rows(res, side="money_out"):
    return {r.name: r for r in getattr(res, side)}


def test_deferred_payment_leaves_its_month_and_lands_on_the_1st_of_the_next(db):
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    _item(db, name="Rent", amount_cents=100_000, day_of_month=1)
    svc.defer_payment(db, loan.id, "2026-09")

    sep = compute_month(db, "2026-09")
    assert _rows(sep)["Loan"].effect == "deferred"
    assert _rows(sep)["Loan"].deferred_to == "2026-10"
    assert sep.totals.out_cents == 100_000  # the loan is not counted

    octo = compute_month(db, "2026-10")
    out = _rows(octo)
    # the regular October payment, plus September's carried-over one
    assert out["Loan"].kind == "recurring" and out["Loan"].effect == "normal"
    carried = [r for r in octo.money_out if r.kind == "carryover"]
    assert [(r.name, r.amount_cents, r.day, r.carried_from) for r in carried] == [
        ("Loan", 20_000, 1, "2026-09")
    ]
    assert octo.totals.out_cents == 100_000 + 20_000 + 20_000


def test_provisioning_ignores_deferrals(db):
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    before = compute_month(db, "2026-10").normalized.out_cents
    svc.defer_payment(db, loan.id, "2026-09")
    assert compute_month(db, "2026-09").normalized.out_cents == before
    assert compute_month(db, "2026-10").normalized.out_cents == before


def test_carrying_again_keeps_rolling_until_paid(db):
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    first = svc.defer_payment(db, loan.id, "2026-09")
    # October: also couldn't pay the carried line
    second = svc.carry_again(db, first.id)
    assert (second.month, second.original_month, second.origin_id) == ("2026-10", "2026-09", first.id)

    octo = compute_month(db, "2026-10")
    carried = next(r for r in octo.money_out if r.kind == "carryover")
    assert carried.effect == "deferred" and carried.deferral_id == second.id
    assert octo.totals.out_cents == 20_000  # only October's own payment counts

    nov = compute_month(db, "2026-11")
    carried = [r for r in nov.money_out if r.kind == "carryover"]
    assert [(r.carried_from, r.effect) for r in carried] == [("2026-09", "normal")]
    assert nov.totals.out_cents == 40_000
    # paid in November (nothing recorded) -> gone in December
    assert not [r for r in compute_month(db, "2026-12").money_out if r.kind == "carryover"]


def test_undo_removes_the_deferral_and_later_carries(db):
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    first = svc.defer_payment(db, loan.id, "2026-09")
    svc.carry_again(db, first.id)
    first_id = first.id
    assert svc.undo_deferral(db, first_id) is True
    assert db.query(models.PaymentDeferral).count() == 0
    assert compute_month(db, "2026-09").totals.out_cents == 20_000
    assert svc.undo_deferral(db, first_id) is False


def test_rules_and_duplicates(db):
    pay = _item(db, name="Pay", amount_cents=500_000, direction="in", day_of_month=1)
    annual = _item(db, name="Insurance", amount_cents=60_000, frequency="annual", anchor_month=3)
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    with pytest.raises(svc.DeferralError):
        svc.defer_payment(db, pay.id, "2026-09")  # income can't be carried
    with pytest.raises(svc.DeferralError):
        svc.defer_payment(db, annual.id, "2026-09")  # not due in September
    svc.defer_payment(db, loan.id, "2026-09")
    with pytest.raises(svc.DeferralError) as e:
        svc.defer_payment(db, loan.id, "2026-09")
    assert e.value.status == 409


def test_multi_payday_items_defer_the_whole_month(db):
    loan = _item(db, name="Biweekly loan", amount_cents=10_000, frequency="biweekly",
                 day_of_week=5, week_anchor=date(2026, 10, 2))
    d = svc.defer_payment(db, loan.id, "2026-10")  # Oct 2, 16, 30
    assert d.amount_cents == 30_000
    assert compute_month(db, "2026-10").totals.out_cents == 0
    nov = compute_month(db, "2026-11")
    assert [r.amount_cents for r in nov.money_out if r.kind == "carryover"] == [30_000]


def test_filters_apply_to_carried_lines(db):
    evan = models.Person(name="Evan", color="#111")
    rach = models.Person(name="Rach", color="#222")
    db.add_all([evan, rach])
    db.commit()
    a = _item(db, name="A", amount_cents=1_000, day_of_month=5, person_id=evan.id)
    b = _item(db, name="B", amount_cents=2_000, day_of_month=5, person_id=rach.id)
    svc.defer_payment(db, a.id, "2026-09")
    svc.defer_payment(db, b.id, "2026-09")
    res = compute_month(db, "2026-10", person_id=rach.id)
    assert [r.name for r in res.money_out if r.kind == "carryover"] == ["B"]


def test_paycheck_lookahead_skips_deferred_and_includes_carried(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=5)
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=28)
    svc.defer_payment(db, loan.id, "2026-09")
    # today Sep 27, paycheck Oct 5: the Sep 28 loan was deferred -> not counted,
    # but it comes back on Oct 1, before the paycheck.
    res = until_next_paycheck(db, date(2026, 9, 27))
    assert [(e["name"], e["kind"], e["date"]) for e in res["before"]] == [
        ("Loan", "carryover", date(2026, 10, 1))
    ]
    assert res["before_total_cents"] == 20_000


def test_api_create_conflict_and_delete(db, client):
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    r = client.post("/api/deferrals", json={"recurring_item_id": loan.id, "month": "2026-09"})
    assert r.status_code == 201 and r.json()["amount_cents"] == 20_000
    assert client.post("/api/deferrals", json={"recurring_item_id": loan.id, "month": "2026-09"}).status_code == 409
    again = client.post("/api/deferrals", json={"origin_id": r.json()["id"]})
    assert again.status_code == 201 and again.json()["month"] == "2026-10"
    assert client.post("/api/deferrals", json={}).status_code == 422
    assert client.post("/api/deferrals", json={"origin_id": 999}).status_code == 404
    assert client.delete(f"/api/deferrals/{r.json()['id']}").status_code == 204
    assert client.delete(f"/api/deferrals/{r.json()['id']}").status_code == 404
    monthly = client.get("/api/monthly", params={"month": "2026-09"}).json()
    assert monthly["totals"]["out_cents"] == 20_000


def test_deleting_the_item_clears_its_deferrals(db):
    from app import crud
    loan = _item(db, name="Loan", amount_cents=20_000, day_of_month=15)
    svc.defer_payment(db, loan.id, "2026-09")
    crud.delete_recurring_item(db, loan.id)
    assert db.query(models.PaymentDeferral).count() == 0
    assert compute_month(db, "2026-10").totals.out_cents == 0


# --- one-off transactions ------------------------------------------------


def _txn(db, **kw):
    kw.setdefault("direction", "out")
    t = models.Transaction(**kw)
    db.add(t)
    db.commit()
    return t


def test_a_one_off_can_be_carried_over_and_rolls_like_a_recurring_item(db):
    couch = _txn(db, date=date(2026, 9, 12), description="Couch", amount_cents=50_000)
    d = svc.defer_transaction(db, couch.id)
    assert (d.month, d.amount_cents, d.recurring_item_id) == ("2026-09", 50_000, None)

    sep = compute_month(db, "2026-09")
    assert _rows(sep)["Couch"].effect == "deferred"
    assert _rows(sep)["Couch"].deferral_id == d.id
    assert sep.totals.out_cents == 0

    octo = compute_month(db, "2026-10")
    carried = [r for r in octo.money_out if r.kind == "carryover"]
    assert [(r.name, r.amount_cents, r.day, r.carried_from) for r in carried] == [
        ("Couch", 50_000, 1, "2026-09")
    ]
    assert octo.totals.out_cents == 50_000

    again = svc.carry_again(db, d.id)
    assert again.transaction_id == couch.id and again.month == "2026-10"
    assert compute_month(db, "2026-10").totals.out_cents == 0
    assert compute_month(db, "2026-11").totals.out_cents == 50_000


def test_one_off_rules_and_cleanup(db):
    paid = _txn(db, date=date(2026, 9, 3), description="Refund", amount_cents=1_000, direction="in")
    couch = _txn(db, date=date(2026, 9, 12), description="Couch", amount_cents=50_000)
    with pytest.raises(svc.DeferralError):
        svc.defer_transaction(db, paid.id)
    svc.defer_transaction(db, couch.id)
    with pytest.raises(svc.DeferralError) as e:
        svc.defer_transaction(db, couch.id)
    assert e.value.status == 409
    from app import crud
    crud.delete_transaction(db, couch.id)
    assert db.query(models.PaymentDeferral).count() == 0


def test_paycheck_lookahead_handles_deferred_and_carried_one_offs(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=5)
    couch = _txn(db, date=date(2026, 9, 28), description="Couch", amount_cents=50_000)
    svc.defer_transaction(db, couch.id)
    res = until_next_paycheck(db, date(2026, 9, 27))
    assert [(e["name"], e["kind"], e["date"]) for e in res["before"]] == [
        ("Couch", "carryover", date(2026, 10, 1))
    ]


def test_api_defers_a_transaction(db, client):
    couch = _txn(db, date=date(2026, 9, 12), description="Couch", amount_cents=50_000)
    r = client.post("/api/deferrals", json={"transaction_id": couch.id})
    assert r.status_code == 201 and r.json()["transaction_id"] == couch.id
    assert client.post("/api/deferrals", json={"transaction_id": couch.id, "month": "2026-09"}).status_code == 422
    assert client.post("/api/deferrals", json={"transaction_id": 999}).status_code == 404
