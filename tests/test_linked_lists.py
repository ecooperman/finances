"""Linked lists: a list from the lists app, forecast as one lump sum exactly like a trip - spread over
the months until the date picked when linking, with exclude / override / mark-paid, all read live.

`fetch_list_costs` is monkeypatched (no live lists call); `set_lists` supplies the rows a real
cost-summary would return (None = the lists app could not be reached)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import crud, models, schemas
from app.deps import get_db
from app.main import app
from app.services import linked_lists as svc
from app.services import trips as trips_service
from app.services.monthly import compute_month


@pytest.fixture()
def set_lists(monkeypatch):
    def _set(rows):
        monkeypatch.setattr(svc, "fetch_list_costs", lambda: rows)
    return _set


def _list(id, name, to_buy, bought=0, **extra):
    return {
        "id": id, "name": name, "total_cost_cents": to_buy + bought, "bought_cents": bought, "to_buy_cents": to_buy,
        "item_count": 5, "open_count": 4, "excluded_count": 0, "unpriced_count": 0, **extra,
    }


def _link(db, list_id=1, name="Move to Portland", due=date(2026, 11, 20)):
    return crud.link_list(db, list_id, name, due)


# --- the same spread as a trip ------------------------------------------------------------


def test_cost_spreads_evenly_until_the_date(db, set_lists):
    set_lists([_list(1, "Move to Portland", 300_000)])
    _link(db)
    row = svc.list_forecasts(db, "2026-08")["upcoming"][0]
    assert (row["months_remaining"], row["monthly_contribution_cents"], row["total_cents"]) == (4, 75_000, 300_000)
    assert row["due_month"] == "2026-11" and row["name"] == "Move to Portland"


def test_a_list_spreads_exactly_like_a_trip_with_the_same_amount_and_month(db, set_lists, monkeypatch):
    set_lists([_list(1, "Move", 250_000)])
    _link(db, due=date(2027, 1, 15))
    monkeypatch.setattr(trips_service, "fetch_trip_costs", lambda: [{
        "id": 9, "location": "Hawaii", "start_date": "2027-01-15T00:00:00", "total_cost_cents": 250_000,
    }])
    for as_of in ("2026-09", "2026-12", "2027-01", "2027-03"):
        lst = svc.list_forecasts(db, as_of)["upcoming"][0]
        trip = trips_service.trip_forecasts(db, as_of)["upcoming"][0]
        assert (lst["months_remaining"], lst["monthly_contribution_cents"]) == (
            trip["months_remaining"], trip["monthly_contribution_cents"]
        ), as_of


def test_no_date_goes_to_its_own_bucket_and_contributes_nothing(db, set_lists):
    set_lists([_list(1, "Move", 100_000)])
    _link(db, due=None)
    fc = svc.list_forecasts(db, "2026-08")
    assert fc["upcoming"] == [] and [r["name"] for r in fc["no_date"]] == ["Move"]
    assert fc["no_date"][0]["monthly_contribution_cents"] == 0


def test_only_what_is_still_to_buy_counts(db, set_lists):
    set_lists([_list(1, "Move", to_buy=70_000, bought=30_000)])
    _link(db)
    row = svc.list_forecasts(db, "2026-09")["upcoming"][0]
    assert row["total_cents"] == 70_000 and row["bought_cents"] == 30_000


# --- the controls --------------------------------------------------------------------------


def test_override_beats_the_computed_total(db, set_lists):
    set_lists([_list(1, "Move", 100_000)])
    _link(db)
    crud.update_linked_list(db, 1, schemas.LinkedListUpdate(override_amount_cents=600_000))
    row = svc.list_forecasts(db, "2026-09")["upcoming"][0]
    assert (row["total_cents"], row["computed_total_cents"]) == (600_000, 100_000)


def test_excluded_is_visible_but_contributes_nothing(db, set_lists):
    set_lists([_list(1, "Move", 100_000)])
    _link(db)
    crud.update_linked_list(db, 1, schemas.LinkedListUpdate(excluded=True))
    fc = svc.list_forecasts(db, "2026-09")
    assert fc["upcoming"] == [] and fc["excluded"][0]["monthly_contribution_cents"] == 0
    assert svc.lists_summary(db, "2026-09") == {"upcoming_count": 0, "monthly_total_cents": 0}


def test_settling_records_a_real_transaction_and_drops_it_from_the_forecast(db, set_lists):
    set_lists([_list(1, "Move", 120_000)])
    _link(db)
    crud.settle_linked_list(db, 1, date(2026, 9, 5), 120_000, "Move")
    assert svc.list_forecasts(db, "2026-09")["upcoming"] == []
    txn = db.query(models.Transaction).one()
    assert (txn.description, txn.amount_cents, txn.direction, txn.date) == ("Move (list)", 120_000, "out", date(2026, 9, 5))
    crud.unsettle_linked_list(db, 1)
    assert db.query(models.Transaction).count() == 0
    assert svc.list_forecasts(db, "2026-09")["upcoming"][0]["name"] == "Move"


# --- reading live --------------------------------------------------------------------------


def test_the_list_name_and_cost_follow_the_lists_app(db, set_lists):
    set_lists([_list(1, "Move", 100_000)])
    _link(db)
    set_lists([_list(1, "Portland move (renamed)", 150_000)])
    row = svc.list_forecasts(db, "2026-09")["upcoming"][0]
    assert (row["name"], row["total_cents"]) == ("Portland move (renamed)", 150_000)


def test_a_list_lists_does_not_report_stays_visible_flagged_missing(db, set_lists):
    set_lists([_list(1, "Move", 100_000)])
    _link(db, name="Move")
    for reported in ([], None):  # deleted or no longer tracking costs / the lists app is unreachable
        set_lists(reported)
        fc = svc.list_forecasts(db, "2026-09")
        row = fc["upcoming"][0]
        assert row["missing"] is True and row["name"] == "Move" and row["monthly_contribution_cents"] == 0
        assert fc["reachable"] is (reported is not None)
    crud.update_linked_list(db, 1, schemas.LinkedListUpdate(override_amount_cents=80_000))
    assert svc.list_forecasts(db, "2026-09")["upcoming"][0]["total_cents"] == 80_000  # an override still counts


def test_only_unlinked_lists_are_offered_to_link(db, set_lists):
    set_lists([_list(1, "Move", 100_000), _list(2, "Wedding", 500_000)])
    _link(db, list_id=1)
    assert svc.list_forecasts(db)["available"] == [{"list_id": 2, "name": "Wedding", "to_buy_cents": 500_000}]


# --- in the monthly numbers ----------------------------------------------------------------


def test_a_linked_list_adds_a_provisioning_row_not_cash_flow(db, set_lists):
    set_lists([_list(1, "Move", 300_000)])
    _link(db, due=date(2026, 11, 20))
    month = compute_month(db, "2026-08")
    # provisioning (normalized) carries the monthly set-aside; real cash flow for the month does not
    assert month.normalized.out_cents == 75_000
    assert month.totals.out_cents == 0
    assert all(r.kind != "list" for r in month.money_out)


# --- the API -------------------------------------------------------------------------------


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_link_edit_settle_and_unlink_over_http(client, set_lists, db):
    set_lists([_list(1, "Move to Portland", 300_000), _list(2, "Wedding", 10_000)])
    assert client.get("/api/linked-lists").json()["available"][0]["name"] == "Move to Portland"

    assert client.post("/api/linked-lists", json={"list_id": 1, "due_date": "2026-11-20"}).status_code == 200
    body = client.get("/api/linked-lists", params={"month": "2026-08"}).json()
    assert [r["name"] for r in body["upcoming"]] == ["Move to Portland"]
    assert [a["name"] for a in body["available"]] == ["Wedding"]
    assert client.get("/api/linked-lists/summary", params={"month": "2026-08"}).json() == {
        "upcoming_count": 1, "monthly_total_cents": 75_000,
    }

    assert client.patch("/api/linked-lists/1", json={"override_amount_cents": 400_000}).json()["override_amount_cents"] == 400_000
    assert client.patch("/api/linked-lists/1", json={"override_amount_cents": 0}).status_code == 422  # positive only
    assert client.patch("/api/linked-lists/1", json={"due_date": "2027-01-10"}).json()["due_date"] == "2027-01-10"

    assert client.post("/api/linked-lists/1/settle", json={"date": "2026-09-01"}).status_code == 200
    assert client.get("/api/linked-lists").json()["upcoming"] == []
    assert client.post("/api/linked-lists/1/unsettle").status_code == 200
    assert client.delete("/api/linked-lists/1").status_code == 200
    assert client.delete("/api/linked-lists/1").status_code == 404


def test_linking_needs_a_reachable_lists_app_and_a_list_that_tracks_costs(client, set_lists):
    set_lists(None)
    assert client.post("/api/linked-lists", json={"list_id": 1}).status_code == 502
    set_lists([_list(1, "Move", 1)])
    assert client.post("/api/linked-lists", json={"list_id": 99}).status_code == 404  # not reported: not tracking costs


def test_linking_twice_keeps_one_link(client, set_lists, db):
    set_lists([_list(1, "Move", 100_000)])
    for _ in range(2):
        assert client.post("/api/linked-lists", json={"list_id": 1, "due_date": "2026-12-01"}).status_code == 200
    assert db.query(models.LinkedList).count() == 1


def test_settling_with_nothing_to_settle_is_refused(client, set_lists):
    set_lists([_list(1, "Move", 0)])
    client.post("/api/linked-lists", json={"list_id": 1, "due_date": "2026-12-01"})
    assert client.post("/api/linked-lists/1/settle", json={"date": "2026-09-01"}).status_code == 400


# --- in a scenario: "the budget without the move" vs "with the move" ------------------------


def _scenario(db, *adjustments):
    sc = models.Scenario(name="Move")
    db.add(sc)
    db.commit()
    for adj in adjustments:
        db.add(models.ScenarioAdjustment(scenario_id=sc.id, kind="add", add_kind="planned", **adj))
    db.commit()
    return sc


def _planned(**extra):
    return dict(name="Move to Portland", link_kind="list", link_id=1, date=date(2026, 11, 20), **extra)


def test_a_scenario_with_a_list_shows_the_set_aside_the_budget_alone_does_not(db, set_lists):
    set_lists([_list(1, "Move to Portland", 300_000)])  # not linked in the real budget
    sc = _scenario(db, _planned())
    month = compute_month(db, "2026-08", scenario_id=sc.id)
    assert month.normalized.out_cents == 0  # the budget without the move
    assert month.scenario.normalized.out_cents == 75_000  # with it: $3,000 over Aug-Nov
    assert month.scenario.totals.out_cents == 0  # provisioning only, like trips: no cash-flow line
    assert all(r.kind != "list" for r in month.scenario.money_out)


def test_it_spreads_by_the_same_rule_as_the_real_budget(db, set_lists):
    set_lists([_list(1, "Move to Portland", 300_000)])
    sc = _scenario(db, _planned())
    with_scenario = compute_month(db, "2026-09", scenario_id=sc.id).scenario.normalized.out_cents
    _link(db)  # now linked in the budget instead
    assert compute_month(db, "2026-09").normalized.out_cents == with_scenario == 100_000


def test_a_list_the_budget_already_counts_is_not_added_twice(db, set_lists):
    set_lists([_list(1, "Move to Portland", 300_000)])
    _link(db)
    sc = _scenario(db, _planned())
    month = compute_month(db, "2026-08", scenario_id=sc.id)
    assert month.normalized.out_cents == month.scenario.normalized.out_cents == 75_000


def test_a_list_left_out_of_the_budget_can_still_be_tried_in_a_scenario(db, set_lists):
    set_lists([_list(1, "Move to Portland", 300_000)])
    _link(db)
    crud.update_linked_list(db, 1, schemas.LinkedListUpdate(excluded=True))
    sc = _scenario(db, _planned())
    month = compute_month(db, "2026-08", scenario_id=sc.id)
    assert (month.normalized.out_cents, month.scenario.normalized.out_cents) == (0, 75_000)


def test_an_override_replaces_the_lists_cost_in_the_scenario(db, set_lists):
    set_lists([_list(1, "Move to Portland", 300_000)])
    sc = _scenario(db, _planned(override_amount_cents=400_000))
    assert compute_month(db, "2026-08", scenario_id=sc.id).scenario.normalized.out_cents == 100_000


def test_a_trip_can_be_planned_in_a_scenario_too(db, monkeypatch):
    monkeypatch.setattr(trips_service, "fetch_trip_costs", lambda: [{
        "id": 9, "location": "Hawaii", "start_date": "2026-11-15T00:00:00", "total_cost_cents": 200_000,
    }])
    crud.update_settlement(db, 9, schemas.TripSettlementUpdate(excluded=True))  # not in the real budget
    sc = _scenario(db, dict(name="Hawaii", link_kind="trip", link_id=9, date=date(2026, 11, 15)))
    month = compute_month(db, "2026-08", scenario_id=sc.id)
    assert (month.normalized.out_cents, month.scenario.normalized.out_cents) == (0, 50_000)


def test_nothing_is_added_while_the_list_has_no_cost_or_is_not_reported(db, set_lists):
    sc = _scenario(db, _planned())
    for reported in ([_list(1, "Move", 0)], [], None):
        set_lists(reported)
        assert compute_month(db, "2026-08", scenario_id=sc.id).scenario.normalized.out_cents == 0


def test_plannable_offers_what_the_budget_is_not_counting(client, set_lists, db, monkeypatch):
    set_lists([_list(1, "Move", 300_000), _list(2, "Wedding", 50_000)])
    monkeypatch.setattr(trips_service, "fetch_trip_costs", lambda: [
        {"id": 9, "location": "Hawaii", "start_date": "2027-01-15T00:00:00", "total_cost_cents": 200_000},
        {"id": 10, "location": "Paris", "start_date": None, "total_cost_cents": 100_000},
    ])
    _link(db, list_id=1)  # counted in the budget: not offered
    offered = {(i["kind"], i["id"]) for i in client.get("/api/scenarios/plannable").json()}
    assert offered == {("list", 2), ("trip", 10)}  # Hawaii has a date, so it is already counted


def test_the_adjustment_needs_its_link_fields(client, db):
    sc = models.Scenario(name="Move")
    db.add(sc)
    db.commit()
    url = f"/api/scenarios/{sc.id}/adjustments"
    body = {"kind": "add", "add_kind": "planned", "name": "Move", "link_kind": "list", "link_id": 1, "date": "2026-11-20"}
    assert client.post(url, json=body).status_code == 200
    for missing in ("link_kind", "link_id", "date", "name"):
        assert client.post(url, json={k: v for k, v in body.items() if k != missing}).status_code == 422, missing
