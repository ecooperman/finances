"""Scenarios can add a hypothetical one-time payment and remove / modify a
real one-off transaction (cash flow only - one-offs aren't provisioned)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import crud, models, schemas
from app.deps import get_db
from app.main import app
from app.services import deferrals
from app.services.monthly import compute_month


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _txn(db, **kw):
    kw.setdefault("direction", "out")
    t = models.Transaction(**kw)
    db.add(t)
    db.commit()
    return t


def _scenario(db, *adjustments):
    s = models.Scenario(name="What if")
    db.add(s)
    db.commit()
    for adj in adjustments:
        db.add(models.ScenarioAdjustment(scenario_id=s.id, **adj))
    db.commit()
    return s


def _row(rows, name):
    return next(r for r in rows if r.name == name)


def test_a_one_time_payment_lands_on_its_day_in_its_month_only(db):
    sc = _scenario(db, dict(kind="add", add_kind="one_time", name="Vet", amount_cents=150_000,
                            direction="out", date=date(2026, 12, 12)))
    dec = compute_month(db, "2026-12", scenario_id=sc.id)
    vet = _row(dec.scenario.money_out, "Vet")
    assert (vet.kind, vet.day, vet.amount_cents, vet.effect) == ("transaction", 12, 150_000, "added")
    assert dec.scenario.delta.out_cents == 150_000 and dec.scenario.delta.net_cents == -150_000
    assert dec.totals.out_cents == 0  # the real month is untouched
    # not in other months
    nov = compute_month(db, "2026-11", scenario_id=sc.id)
    assert nov.scenario.delta.out_cents == 0 and not nov.scenario.money_out


def test_a_one_time_payment_never_touches_provisioning(db):
    sc = _scenario(db, dict(kind="add", add_kind="one_time", name="Vet", amount_cents=150_000,
                            direction="out", date=date(2026, 12, 12)))
    res = compute_month(db, "2026-12", scenario_id=sc.id)
    assert res.scenario.normalized_delta.net_cents == 0


def test_a_one_time_income_counts_as_money_in(db):
    sc = _scenario(db, dict(kind="add", add_kind="one_time", name="Bonus", amount_cents=200_000,
                            direction="in", date=date(2026, 12, 20)))
    res = compute_month(db, "2026-12", scenario_id=sc.id)
    assert _row(res.scenario.money_in, "Bonus").day == 20
    assert res.scenario.delta.net_cents == 200_000


def test_filters_apply_to_a_one_time_payment(db):
    p = models.Person(name="Rach", color="#111")
    q = models.Person(name="Evan", color="#222")
    db.add_all([p, q])
    db.commit()
    sc = _scenario(db, dict(kind="add", add_kind="one_time", name="Vet", amount_cents=1_000,
                            direction="out", date=date(2026, 12, 12), person_id=p.id))
    assert compute_month(db, "2026-12", person_id=p.id, scenario_id=sc.id).scenario.money_out
    assert not compute_month(db, "2026-12", person_id=q.id, scenario_id=sc.id).scenario.money_out


def test_a_scenario_can_remove_a_real_one_off(db):
    couch = _txn(db, date=date(2026, 12, 3), description="Couch", amount_cents=200_000)
    _txn(db, date=date(2026, 12, 5), description="Gas", amount_cents=5_000)
    sc = _scenario(db, dict(kind="remove", target_transaction_id=couch.id))
    res = compute_month(db, "2026-12", scenario_id=sc.id)
    assert _row(res.scenario.money_out, "Couch").effect == "removed"
    assert res.totals.out_cents == 205_000                      # reality unchanged
    assert res.scenario.totals.out_cents == 5_000
    assert res.scenario.delta.out_cents == -200_000
    assert res.scenario.normalized_delta.net_cents == 0         # one-offs aren't provisioned


def test_a_scenario_can_scale_or_override_a_real_one_off(db):
    couch = _txn(db, date=date(2026, 12, 3), description="Couch", amount_cents=200_000)
    scale = _scenario(db, dict(kind="modify", target_transaction_id=couch.id, multiplier=0.5))
    row = _row(compute_month(db, "2026-12", scenario_id=scale.id).scenario.money_out, "Couch")
    assert (row.amount_cents, row.original_amount_cents, row.effect) == (100_000, 200_000, "modified")
    exact = _scenario(db, dict(kind="modify", target_transaction_id=couch.id, override_amount_cents=75_000))
    res = compute_month(db, "2026-12", scenario_id=exact.id)
    assert _row(res.scenario.money_out, "Couch").amount_cents == 75_000
    assert res.scenario.delta.out_cents == -125_000


def test_a_change_to_a_transaction_in_another_month_does_nothing(db):
    couch = _txn(db, date=date(2026, 12, 3), description="Couch", amount_cents=200_000)
    sc = _scenario(db, dict(kind="remove", target_transaction_id=couch.id))
    nov = compute_month(db, "2026-11", scenario_id=sc.id)
    assert nov.scenario.delta.net_cents == 0


def test_a_carried_over_one_off_is_left_alone_by_scenarios(db):
    couch = _txn(db, date=date(2026, 12, 3), description="Couch", amount_cents=200_000)
    deferrals.defer_transaction(db, couch.id)
    sc = _scenario(db, dict(kind="remove", target_transaction_id=couch.id))
    row = _row(compute_month(db, "2026-12", scenario_id=sc.id).scenario.money_out, "Couch")
    assert row.effect == "deferred"


def test_adjustment_shape_rules():
    ok = dict(kind="add", add_kind="one_time", name="Vet", amount_cents=1, direction="out",
              date=date(2026, 12, 1))
    assert schemas.ScenarioAdjustmentCreate(**ok).date == date(2026, 12, 1)
    with pytest.raises(Exception):
        schemas.ScenarioAdjustmentCreate(**{**ok, "date": None})       # a date is required
    with pytest.raises(Exception):
        schemas.ScenarioAdjustmentCreate(kind="remove")                # no target
    with pytest.raises(Exception):
        schemas.ScenarioAdjustmentCreate(kind="remove", target_recurring_id=1, target_transaction_id=2)
    assert schemas.ScenarioAdjustmentCreate(kind="remove", target_transaction_id=2).target_transaction_id == 2
    with pytest.raises(Exception):
        schemas.ScenarioAdjustmentCreate(kind="modify", target_transaction_id=2)   # needs how


def test_api_add_and_describe_adjustments_and_cleanup_on_delete(db, client):
    couch = _txn(db, date=date(2026, 12, 3), description="Couch", amount_cents=200_000)
    sid = client.post("/api/scenarios", json={"name": "Lean December"}).json()["id"]
    a = client.post(f"/api/scenarios/{sid}/adjustments", json={
        "kind": "add", "add_kind": "one_time", "name": "Vet", "amount_cents": 150_000,
        "direction": "out", "date": "2026-12-12"})
    assert a.status_code in (200, 201)
    b = client.post(f"/api/scenarios/{sid}/adjustments", json={"kind": "remove", "target_transaction_id": couch.id})
    assert b.status_code in (200, 201)
    sc = client.get(f"/api/scenarios/{sid}").json()
    by_kind = {x["kind"]: x for x in sc["adjustments"]}
    assert by_kind["add"]["date"] == "2026-12-12"
    assert by_kind["remove"]["target_transaction"]["description"] == "Couch"
    monthly = client.get("/api/monthly", params={"month": "2026-12", "scenario_id": sid}).json()
    assert monthly["scenario"]["delta"]["out_cents"] == 150_000 - 200_000
    crud.delete_transaction(db, couch.id)
    left = client.get(f"/api/scenarios/{sid}").json()["adjustments"]
    assert [x["kind"] for x in left] == ["add"]


# --- the scenario's one-time total (the "what will this cost" figure) -------


def _add_one_time(client, scenario_id, name, cents, day, direction="out"):
    r = client.post(f"/api/scenarios/{scenario_id}/adjustments", json={
        "kind": "add", "add_kind": "one_time", "name": name, "amount_cents": cents,
        "direction": direction, "date": day,
    })
    assert r.status_code == 200, r.text


def test_a_scenario_with_no_one_time_lines_totals_zero(client):
    sid = client.post("/api/scenarios", json={"name": "Empty"}).json()["id"]
    one_time = client.get(f"/api/scenarios/{sid}").json()["one_time"]
    assert one_time == {"count": 0, "out_cents": 0, "in_cents": 0, "cost_cents": 0, "by_month": []}


def test_one_time_lines_are_totalled_overall_and_by_month_in_date_order(client):
    sid = client.post("/api/scenarios", json={"name": "Move"}).json()["id"]
    _add_one_time(client, sid, "Deposit", 200_000, "2027-01-05")
    _add_one_time(client, sid, "Truck", 240_000, "2026-12-15")
    _add_one_time(client, sid, "Boxes", 8_000, "2026-12-01")
    one_time = client.get(f"/api/scenarios/{sid}").json()["one_time"]
    assert one_time["count"] == 3
    assert (one_time["out_cents"], one_time["cost_cents"]) == (448_000, 448_000)
    assert one_time["by_month"] == [
        {"month": "2026-12", "out_cents": 248_000, "in_cents": 0},
        {"month": "2027-01", "out_cents": 200_000, "in_cents": 0},
    ]


def test_money_in_reduces_the_cost(client):
    sid = client.post("/api/scenarios", json={"name": "Move"}).json()["id"]
    _add_one_time(client, sid, "Truck", 240_000, "2026-12-15")
    _add_one_time(client, sid, "Sell the couch", 30_000, "2026-12-10", direction="in")
    one_time = client.get(f"/api/scenarios/{sid}").json()["one_time"]
    assert (one_time["out_cents"], one_time["in_cents"], one_time["cost_cents"]) == (240_000, 30_000, 210_000)


def test_only_one_time_additions_count(client, db):
    sid = client.post("/api/scenarios", json={"name": "Mixed"}).json()["id"]
    _add_one_time(client, sid, "Truck", 240_000, "2026-12-15")
    client.post(f"/api/scenarios/{sid}/adjustments", json={
        "kind": "add", "add_kind": "recurring", "name": "New rent", "amount_cents": 250_000, "direction": "out",
        "frequency": "monthly",
    })
    client.post(f"/api/scenarios/{sid}/adjustments", json={
        "kind": "add", "add_kind": "fund", "name": "Move fund", "amount_cents": 120_000,
    })
    one_time = client.get(f"/api/scenarios/{sid}").json()["one_time"]
    assert (one_time["count"], one_time["cost_cents"]) == (1, 240_000)


def test_the_total_is_in_the_scenario_list_too(client):
    sid = client.post("/api/scenarios", json={"name": "Move"}).json()["id"]
    _add_one_time(client, sid, "Truck", 240_000, "2026-12-15")
    listed = next(s for s in client.get("/api/scenarios").json() if s["id"] == sid)
    assert listed["one_time"]["cost_cents"] == 240_000


# --- editing a line (the page re-sends the whole line) ----------------------


def _one_time_body(name, cents, day, direction="out"):
    return {"kind": "add", "add_kind": "one_time", "name": name, "amount_cents": cents,
            "direction": direction, "date": day}


def test_editing_a_one_time_line_changes_the_total_and_the_month(client):
    sid = client.post("/api/scenarios", json={"name": "Move"}).json()["id"]
    adj = client.post(f"/api/scenarios/{sid}/adjustments", json=_one_time_body("Truck", 240_000, "2026-12-15")).json()
    r = client.patch(f"/api/adjustments/{adj['id']}", json=_one_time_body("Bigger truck", 300_000, "2027-01-03"))
    assert r.status_code == 200 and r.json()["name"] == "Bigger truck"
    one_time = client.get(f"/api/scenarios/{sid}").json()["one_time"]
    assert one_time["cost_cents"] == 300_000
    assert one_time["by_month"] == [{"month": "2027-01", "out_cents": 300_000, "in_cents": 0}]


def test_turning_a_one_time_line_into_a_recurring_one_drops_it_from_the_total(client):
    sid = client.post("/api/scenarios", json={"name": "Move"}).json()["id"]
    adj = client.post(f"/api/scenarios/{sid}/adjustments", json=_one_time_body("Rent", 250_000, "2026-12-15")).json()
    r = client.patch(f"/api/adjustments/{adj['id']}", json={
        "kind": "add", "add_kind": "recurring", "name": "Rent", "amount_cents": 250_000, "direction": "out",
        "frequency": "monthly",
    })
    assert r.status_code == 200
    saved = client.get(f"/api/scenarios/{sid}").json()
    assert saved["one_time"]["count"] == 0
    assert saved["adjustments"][0]["date"] is None  # nothing left over from the old shape


def test_an_edit_that_breaks_the_rules_is_refused_and_leaves_the_line_alone(client):
    sid = client.post("/api/scenarios", json={"name": "Move"}).json()["id"]
    adj = client.post(f"/api/scenarios/{sid}/adjustments", json=_one_time_body("Truck", 240_000, "2026-12-15")).json()
    bad = client.patch(f"/api/adjustments/{adj['id']}", json={"kind": "add", "add_kind": "one_time", "name": "Truck",
                                                              "amount_cents": 240_000, "direction": "out"})  # no date
    assert bad.status_code == 422
    assert client.get(f"/api/scenarios/{sid}").json()["one_time"]["cost_cents"] == 240_000
