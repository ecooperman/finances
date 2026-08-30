"""Trip cost forecasting - amortization, filtering, and the settle flow.

`fetch_trip_costs` is monkeypatched (no live trip-planning call); the
`set_trips` fixture supplies the rows a real cost-summary would return.
"""

from datetime import date

import pytest

from app import crud, models, schemas
from app.services import trips as trips_service
from app.services.monthly import compute_month


@pytest.fixture()
def set_trips(monkeypatch):
    def _set(rows):
        trips_service._cache["data"] = None
        trips_service._cache["at"] = 0.0
        monkeypatch.setattr(trips_service, "fetch_trip_costs", lambda: rows)
    return _set


def _trip(id, location, start, total_cents):
    return {
        "id": id,
        "location": location,
        "city": None,
        "start_date": f"{start}T00:00:00" if start else None,
        "end_date": None,
        "activities_cost_cents": 0,
        "stays_cost_cents": total_cents,
        "total_cost_cents": total_cents,
    }


# --- amortization ---------------------------------------------------


def test_cost_spreads_evenly_until_the_trip(db, set_trips):
    set_trips([_trip(1, "Hawaii", "2026-11", 300_000)])  # 3 months out from Aug
    fc = trips_service.trip_forecasts(db, "2026-08")
    row = fc["upcoming"][0]
    assert row["months_remaining"] == 4  # Aug, Sep, Oct, Nov inclusive
    assert row["monthly_contribution_cents"] == 75_000
    assert row["total_cents"] == 300_000


def test_trip_month_gets_the_full_remaining(db, set_trips):
    set_trips([_trip(1, "Hawaii", "2026-11", 300_000)])
    row = trips_service.trip_forecasts(db, "2026-11")["upcoming"][0]
    assert row["months_remaining"] == 1
    assert row["monthly_contribution_cents"] == 300_000


def test_overdue_trip_is_all_due_now(db, set_trips):
    set_trips([_trip(1, "Past trip", "2026-06", 120_000)])
    row = trips_service.trip_forecasts(db, "2026-09")["upcoming"][0]
    assert row["monthly_contribution_cents"] == 120_000


def test_no_date_trip_goes_to_its_own_bucket(db, set_trips):
    set_trips([_trip(1, "Someday", None, 500_00)])
    fc = trips_service.trip_forecasts(db, "2026-08")
    assert fc["upcoming"] == []
    assert [r["name"] for r in fc["no_date"]] == ["Someday"]
    assert fc["no_date"][0]["monthly_contribution_cents"] == 0


# --- settlement state --------------------------------------------


def test_override_beats_the_computed_total(db, set_trips):
    set_trips([_trip(1, "Hawaii", "2026-10", 100_000)])
    crud.update_settlement(db, 1, schemas.TripSettlementUpdate(override_amount_cents=600_000))
    row = trips_service.trip_forecasts(db, "2026-08")["upcoming"][0]
    assert row["total_cents"] == 600_000
    assert row["computed_total_cents"] == 100_000


def test_excluded_and_settled_trips_are_dropped(db, set_trips):
    set_trips([
        _trip(1, "Excluded", "2026-10", 100_000),
        _trip(2, "Settled", "2026-10", 100_000),
        _trip(3, "Live", "2026-10", 100_000),
    ])
    crud.update_settlement(db, 1, schemas.TripSettlementUpdate(excluded=True))
    crud.settle_trip(db, 2, date(2026, 8, 15), 100_000, "Settled", None)
    names = [r["name"] for r in trips_service.trip_forecasts(db, "2026-08")["upcoming"]]
    assert names == ["Live"]


# --- aggregation ------------------------------------------------


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


def test_trips_hit_provisioning_not_cash_flow(db, set_trips):
    _recurring(db)  # monthly $3,000 mortgage - lands in cash flow
    set_trips([_trip(1, "Hawaii", "2026-10", 300_000)])  # Aug->Oct = 3 months -> 100k/mo
    res = compute_month(db, "2026-08")
    assert res.totals.out_cents == 300_000  # cash flow: just the mortgage, no trip
    assert res.normalized.out_cents == 300_000 + 100_000  # mortgage smoothed + trip share


def test_person_filter_drops_trip_rows(db, set_trips):
    person = models.Person(name="Evan", color="#111")
    db.add(person)
    db.commit()
    set_trips([_trip(1, "Hawaii", "2026-10", 300_000)])
    everyone = compute_month(db, "2026-08")
    assert everyone.normalized.out_cents == 100_000
    scoped = compute_month(db, "2026-08", person_id=person.id)
    assert scoped.normalized.out_cents == 0  # trips are household, filtered out
    joint = compute_month(db, "2026-08", joint_only=True)
    assert joint.normalized.out_cents == 100_000


# --- settle flow ------------------------------------------------


def test_settle_creates_a_transaction_and_unsettle_removes_it(db, set_trips):
    set_trips([_trip(7, "Portland", "2026-09", 180_000)])
    s = crud.settle_trip(db, 7, date(2026, 9, 3), 180_000, "Portland", None)
    assert s.settled_at is not None
    txn = crud.get_transaction(db, s.settled_transaction_id)
    assert txn.description == "Portland (trip)"
    assert txn.amount_cents == 180_000
    assert txn.direction == "out"
    assert txn.date == date(2026, 9, 3)
    # settled -> gone from the forecast
    assert trips_service.trip_forecasts(db, "2026-08")["upcoming"] == []

    crud.unsettle_trip(db, 7)
    assert crud.get_transaction(db, txn.id) is None
    assert [r["name"] for r in trips_service.trip_forecasts(db, "2026-08")["upcoming"]] == ["Portland"]
