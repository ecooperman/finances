"""The optional Reference ID field on recurring items and its dedupe check.

Providers name it differently (Affirm "loan id", Klarna "order reference",
PayPal something else) - it's just a free-text unique key here.
"""

import pytest
from fastapi.testclient import TestClient

from app import crud, schemas
from app.deps import get_db
from app.main import app


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _payload(**over):
    base = {"name": "Affirm - couch", "amount_cents": 12000, "direction": "out", "frequency": "monthly"}
    base.update(over)
    return base


# --- crud-level -----------------------------------------------------


def test_conflict_lookup(db):
    a = crud.create_recurring_item(db, schemas.RecurringItemCreate(**_payload(reference_id="AFF-123")))
    assert crud.recurring_reference_id_conflict(db, "AFF-123") is a
    assert crud.recurring_reference_id_conflict(db, "AFF-123", exclude_id=a.id) is None
    assert crud.recurring_reference_id_conflict(db, "OTHER") is None
    assert crud.recurring_reference_id_conflict(db, None) is None
    assert crud.recurring_reference_id_conflict(db, "") is None


def test_blank_reference_id_normalizes_to_none(db):
    item = crud.create_recurring_item(db, schemas.RecurringItemCreate(**_payload(reference_id="  ")))
    assert item.reference_id is None


# --- API-level -----------------------------------------------------


def test_duplicate_reference_id_is_rejected_on_create(client):
    assert client.post("/api/recurring", json=_payload(reference_id="KL-9")).status_code == 200
    dup = client.post("/api/recurring", json=_payload(name="Klarna - again", reference_id="KL-9"))
    assert dup.status_code == 409
    assert "KL-9" in dup.json()["detail"]
    assert "Affirm - couch" in dup.json()["detail"]


def test_many_items_without_a_reference_id_are_fine(client):
    for i in range(3):
        assert client.post("/api/recurring", json=_payload(name=f"item {i}")).status_code == 200


def test_patching_a_reference_id_onto_a_second_item_is_rejected(client):
    client.post("/api/recurring", json=_payload(reference_id="PP-1"))
    other = client.post("/api/recurring", json=_payload(name="Other")).json()
    resp = client.patch(f"/api/recurring/{other['id']}", json={"reference_id": "PP-1"})
    assert resp.status_code == 409


def test_saving_an_item_with_its_own_unchanged_reference_id_is_allowed(client):
    made = client.post("/api/recurring", json=_payload(reference_id="AFF-7")).json()
    resp = client.patch(f"/api/recurring/{made['id']}", json={"amount_cents": 9999, "reference_id": "AFF-7"})
    assert resp.status_code == 200
    assert resp.json()["reference_id"] == "AFF-7"
