"""The numbers the dashboard's stats pages read: administrators only, counts and dates only (never an amount or a name), everyone's accounts."""
from app import models
from tests.test_accounts import BOB, OWNER, SECRET, client_for, key, make_user, production, two_people  # noqa: F401 - fixtures


def test_only_an_administrator_can_read_the_stats(two_people, client_for):
    assert client_for(BOB).get("/api/admin/stats").status_code == 403
    assert client_for(OWNER).get("/api/admin/stats").status_code == 200


def test_the_stats_count_everyones_things_without_showing_any_of_them(two_people, client_for):
    body = client_for(OWNER).get("/api/admin/stats")
    accounts = {a["email"]: a for a in body.json()["accounts"]}
    assert set(accounts) == {OWNER, BOB}
    assert sum(accounts[BOB]["counts"].values()) > 0 and sum(accounts[OWNER]["counts"].values()) > 0
    assert accounts[BOB]["counts"]["categories"] > 0  # every account is made with the default categories
    assert SECRET not in body.text and "SECRET-BOB" not in body.text


def test_the_gate_notes_when_a_person_was_last_seen(two_people, client_for, production):
    assert client_for(BOB).get("/api/me").status_code == 200
    from shared_python import owned

    with owned.unscoped(), production() as db:
        user = db.query(models.User).filter(models.User.email == BOB).one()
        assert user.active_days == 1 and user.last_seen_at is not None
