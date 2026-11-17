"""Several people can have an account, and each one's finances are completely private to them. This is the household budget,
so the point of this file is that NOTHING one person does, with any id, in any route, can read or change another's money.

* Default-deny: nobody without an account gets anything, whether signed out, a signed-in stranger, or someone removed.
* The two-person sweep: a second person with a valid account calls EVERY route of the app, naming the first person's ids in
  the path and in the body. None may answer with the first person's data, none may change it, and an id that is not theirs
  is refused. A route added later must be listed in SPEC (a test fails until it is), so it cannot slip past unexamined.
* Reading is filtered below the routes (shared_python.owned), writes that would cross over are refused there too, and
  the trip forecast and linked lists, which read the ADMINISTRATOR's other apps with their service tokens, give anyone else
  nothing."""
import sqlite3
import time
from contextlib import contextmanager
from datetime import date

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from shared_python import auth, owned, settings
from sqlalchemy import inspect as sa_inspect

from app import config, crud, models, notify
from app.deps import get_db
from app.main import app
from app.seed import DEFAULT_CATEGORIES, seed_categories
from app.services import linked_lists as lists_service
from app.services import trips as trips_service
from app.services.linked_lists import fetch_list_costs as REAL_FETCH_LISTS
from app.services.trips import fetch_trip_costs as REAL_FETCH_TRIPS  # the autouse fixtures replace the module's own

ISSUER = "https://login.example.com"
CLIENT = "client-123"
FRONT = "https://dashboard.example.org"
OWNER, BOB, STRANGER = "owner@example.com", "bob@example.com", "stranger@example.com"
PAGES = ["/", "/budget.html", "/scenarios.html", "/settings.html", "/users.html"]
SECRET = "SECRET-OWNER"  # in every piece of the owner's data: it must never reach anyone else
ALL_MODELS = [
    models.Person, models.Category, models.RecurringItem, models.Transaction, models.SinkingFund, models.TripSettlement,
    models.LinkedList, models.PaymentDeferral, models.DailySpend, models.MonthOpeningBalance, models.AppSetting,
    models.Scenario, models.ScenarioAdjustment,
]


# --- the world: accounts, sign-in and a full set of data per person ----------------------------------------------------


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def production(monkeypatch, key, world):
    """The app as deployed: signed-in people only, through the front door, with OWNER as the administrator. Requests
    use the test database."""

    def get_test_db():
        session = world()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_test_db
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(config, "ADMIN_EMAILS", {OWNER})
    monkeypatch.setattr(settings, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", CLIENT)
    monkeypatch.setattr(settings, "OIDC_LOGIN_URL", FRONT + "/auth/login")
    monkeypatch.setattr(auth, "_oidc_signing_key", lambda _t: key.public_key())
    yield world
    app.dependency_overrides.clear()


def session_for(key, email):
    return jwt.encode(
        {"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 300, "email": email, "email_verified": True}, key, algorithm="RS256"
    )


@pytest.fixture()
def client_for(production, key):
    def make(email=None):
        client = TestClient(app, base_url="https://finances.example.org", follow_redirects=False)
        if email:
            client.cookies.set("oidc_session", session_for(key, email))
        return client

    return make


@pytest.fixture()
def make_user(production):
    """make_user("bob@example.com") -> the new person's id (an account: they have been let in), with the default categories
    every new account gets."""

    def make(email, status=models.USER_ACTIVE):
        with owned.unscoped(), production() as session:
            user = models.User(email=email, status=status)
            session.add(user)
            session.commit()
            user_id = user.id
        with owned.scope(user_id), production() as db:
            seed_categories(db)
        return user_id

    return make


@contextmanager
def working_as(factory, person_id):
    with owned.scope(person_id), factory() as session:
        yield session


def fill(factory, person_id, tag):
    """A full set of data for one person, one row in every table, every text carrying `tag`. Returns the ids."""
    with working_as(factory, person_id) as db:
        person = models.Person(name=f"{tag}-person", color="#111111")
        category = models.Category(name=f"{tag}-category", color="#222222", text_color="light", sort_order=900)
        db.add_all([person, category])
        db.flush()
        item = models.RecurringItem(name=f"{tag}-rent", amount_cents=150000, direction="out", frequency="monthly", active=True,
                                    day_of_month=5, category_id=category.id, person_id=person.id, reference_id=f"{tag}-ref")
        daily = models.RecurringItem(name=f"{tag}-groceries", amount_cents=30000, direction="out", frequency="monthly",
                                     active=True, spread_daily=True)
        fund = models.SinkingFund(name=f"{tag}-fund", annual_amount_cents=120000, start_month="2026-01", active=True)
        db.add_all([item, daily, fund])
        db.flush()
        txn = models.Transaction(date=date(2026, 11, 10), description=f"{tag}-purchase", amount_cents=4200, direction="out",
                                 category_id=category.id, person_id=person.id, fund_id=fund.id)
        scenario = models.Scenario(name=f"{tag}-what-if", notes=f"{tag}-note")
        db.add_all([txn, scenario])
        db.flush()
        adjustment = models.ScenarioAdjustment(scenario_id=scenario.id, kind="add", add_kind="recurring", name=f"{tag}-extra",
                                               amount_cents=9900, direction="out", frequency="monthly")
        deferral = models.PaymentDeferral(recurring_item_id=item.id, month="2026-11", original_month="2026-11", amount_cents=150000)
        spend = models.DailySpend(recurring_item_id=daily.id, date=date(2026, 11, 10), amount_cents=1234, note=f"{tag}-coffee")
        opening = models.MonthOpeningBalance(month="2026-11", amount_cents=500000, note=f"{tag}-bank")
        setting = models.AppSetting(key="rollover_start_month", value="2026-10")
        trip = models.TripSettlement(trip_id=77, note=f"{tag}-trip-note")
        link = models.LinkedList(list_id=88, name=f"{tag}-linked")
        db.add_all([adjustment, deferral, spend, opening, setting, trip, link])
        db.commit()
        return {
            "person": person.id, "cat": category.id, "item": item.id, "daily": daily.id, "fund": fund.id, "txn": txn.id,
            "scenario": scenario.id, "adj": adjustment.id, "deferral": deferral.id, "spend": spend.id, "month": "2026-11",
            "trip": 77, "list": 88,
        }


def snapshot(factory, person_id):
    """Everything one person owns, as plain values, to compare before and after."""
    out = {}
    with working_as(factory, person_id) as db:
        for model in ALL_MODELS:
            columns = [c.key for c in sa_inspect(model).columns]
            out[model.__name__] = sorted(
                (tuple(str(getattr(row, c)) for c in columns) for row in db.query(model).all())
            )
    return out


@pytest.fixture()
def two_people(production, make_user):
    """The administrator (OWNER) and an ordinary person (BOB), each with a full set of private data."""
    owner_id, bob_id = make_user(OWNER), make_user(BOB)
    return {
        "factory": production, "owner_id": owner_id, "bob_id": bob_id,
        "owner": fill(production, owner_id, SECRET), "bob": fill(production, bob_id, "SECRET-BOB"),
    }


# --- nobody without an account gets anything --------------------------------------------------------------------------


def every_route():
    for shown, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.upper() not in ("HEAD", "OPTIONS"):
                yield method.upper(), shown, shown.replace("{", "1__").replace("}", "")  # a stand-in id


def concrete(shown):
    import re

    return re.sub(r"\{[^}]+\}", "1", shown)


def call(client, method, shown, **kw):
    if method in ("POST", "PUT", "PATCH") and "json" not in kw:
        kw["json"] = {}
    return client.request(method, concrete(shown), **kw)


def test_there_are_routes_to_sweep():
    assert len(list(every_route())) > 55  # guards against the sweep silently covering nothing


def test_nobody_signed_out_gets_anything_from_any_route(two_people, client_for):
    client = client_for()
    answered = []
    for method, shown, _ in every_route():
        resp = call(client, method, shown)
        if resp.status_code not in (401, 302) or SECRET in resp.text:
            answered.append((method, shown, resp.status_code))
    for page in PAGES + ["/app.js", "/budget.js", "/scenarios.js", "/settings.js", "/users.js", "/common.js", "/nav.js", "/style.css", "/version.js", "/manifest.json", "/sw.js", "/nope"]:
        resp = client.get(page)
        if resp.status_code != 302:
            answered.append(("GET", page, resp.status_code))
    assert not answered, f"answered with no sign-in: {answered}"


def test_signing_in_is_not_enough_a_stranger_gets_nothing_from_any_route(two_people, client_for):
    client = client_for(STRANGER)
    answered = []
    for method, shown, _ in every_route():
        resp = call(client, method, shown)
        if resp.status_code != 403 or SECRET in resp.text:
            answered.append((method, shown, resp.status_code))
    assert not answered, f"answered a signed-in stranger: {answered}"
    page = client.get("/")
    assert page.status_code == 403 and "have access yet" in page.text and client.get("/app.js").status_code == 403


def test_a_removed_person_gets_nothing_either(two_people, client_for, make_user):
    make_user("gone@example.com", status=models.USER_REMOVED)
    client = client_for("gone@example.com")
    assert all(call(client, m, s).status_code == 403 for m, s, _ in every_route())
    assert "access was removed" in client.get("/").text


def test_nothing_is_public_not_even_a_manifest_or_icons(two_people, client_for):
    client = client_for()
    for path in ("/manifest.json", "/icons/icon-192.png", "/sw.js", "/robots.txt"):
        assert client.get(path).status_code == 302


def test_a_service_token_for_another_app_opens_nothing(two_people, client_for, monkeypatch):
    monkeypatch.setattr(config, "TRIPS_SERVICE_TOKEN", "trips-secret")
    monkeypatch.setattr(config, "LISTS_SERVICE_TOKEN", "lists-secret")
    client = client_for()
    for token in ("trips-secret", "lists-secret"):
        for path in ("/api/people", "/api/recurring", "/api/monthly"):
            assert client.get(path, headers={"X-Service-Token": token}).status_code == 401


def test_a_forged_or_expired_session_is_signed_out(two_people, client_for, key):
    client = client_for()
    client.cookies.set("oidc_session", session_for(key, OWNER).replace(".", "x.", 1))
    assert client.get("/api/people").status_code == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client.cookies.set("oidc_session", session_for(other, OWNER))  # right address, signed by someone else
    assert client.get("/api/people").status_code == 401


def test_an_unverified_email_never_signs_anyone_in(two_people, client_for, key):
    client = client_for()
    token = jwt.encode({"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 300, "email": OWNER, "email_verified": False}, key, algorithm="RS256")
    client.cookies.set("oidc_session", token)
    assert client.get("/api/people").status_code in (401, 403)


def test_without_an_administrator_configured_nobody_without_an_account_gets_in(two_people, client_for, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    assert client_for("newcomer@example.com").get("/api/people").status_code == 403


def test_the_bare_email_is_matched_whatever_its_case(two_people, client_for):
    assert client_for("Bob@Example.COM").get("/api/people").status_code in (200, 403)  # never someone else's data
    resp = client_for("Bob@Example.COM").get("/api/recurring")
    assert SECRET not in resp.text


# --- the two-person sweep ------------------------------------------------------------------------------------------------
# kind: "own"   - acts on the caller's own data (a list, a create): may succeed, but never shows or changes the owner's
#       "by_id" - names the OWNER's id, in the path or the body: must be refused (400/403/404), changing nothing
#       "admin" - only for administrators: a member is refused with 403 whatever it asks


def by_id(**body):
    return ("by_id", lambda a: body)


def own(**kw):
    return ("own", lambda a: kw)


SPEC = {
    ("GET", "/api/version"): own(),
    ("GET", "/api/me"): own(),
    ("GET", "/api/categories"): own(),
    ("POST", "/api/categories"): own(json={"name": "Bob-new-category"}),
    # an id that is not the caller's is simply skipped (the filter never finds it): nothing of the owner's is shown or moved,
    # which the sweep's two checks below prove, so this is "own" rather than "refused"
    ("POST", "/api/categories/reorder"): ("own", lambda a: {"json": {"ordered_ids": [a["cat"]]}}),
    ("PATCH", "/api/categories/{category_id}"): ("by_id", lambda a: {"json": {"name": "hijacked"}}),
    ("DELETE", "/api/categories/{category_id}"): ("by_id", lambda a: {}),
    ("GET", "/api/people"): own(),
    ("POST", "/api/people"): own(json={"name": "Bob-new-person"}),
    ("PATCH", "/api/people/{person_id}"): ("by_id", lambda a: {"json": {"name": "hijacked"}}),
    ("DELETE", "/api/people/{person_id}"): ("by_id", lambda a: {}),
    ("GET", "/api/recurring"): own(),
    ("GET", "/api/recurring/summary"): own(),
    ("POST", "/api/recurring"): ("by_id", lambda a: {"json": {"name": "x", "amount_cents": 100, "direction": "out", "category_id": a["cat"]}}),
    ("PATCH", "/api/recurring/{item_id}"): ("by_id", lambda a: {"json": {"name": "hijacked", "amount_cents": 1}}),
    ("DELETE", "/api/recurring/{item_id}"): ("by_id", lambda a: {}),
    ("POST", "/api/recurring/{item_id}/convert-to-transaction"): ("by_id", lambda a: {"json": {"date": "2026-11-12"}}),
    ("GET", "/api/transactions"): own(),
    ("POST", "/api/transactions"): ("by_id", lambda a: {"json": {"date": "2026-11-12", "description": "x", "amount_cents": 100, "direction": "out", "fund_id": a["fund"]}}),
    ("PATCH", "/api/transactions/{txn_id}"): ("by_id", lambda a: {"json": {"description": "hijacked"}}),
    ("DELETE", "/api/transactions/{txn_id}"): ("by_id", lambda a: {}),
    ("POST", "/api/transactions/{txn_id}/convert-to-recurring"): ("by_id", lambda a: {"json": {"frequency": "monthly"}}),
    ("GET", "/api/funds"): own(),
    ("GET", "/api/funds/summary"): own(),
    ("POST", "/api/funds"): ("by_id", lambda a: {"json": {"name": "x", "annual_amount_cents": 1200, "person_id": a["person"]}}),
    ("PATCH", "/api/funds/{fund_id}"): ("by_id", lambda a: {"json": {"name": "hijacked"}}),
    ("DELETE", "/api/funds/{fund_id}"): ("by_id", lambda a: {}),
    ("GET", "/api/scenarios"): own(),
    ("POST", "/api/scenarios"): own(json={"name": "Bob-what-if"}),
    ("GET", "/api/scenarios/plannable"): own(),
    ("GET", "/api/scenarios/{scenario_id}"): ("by_id", lambda a: {}),
    ("PATCH", "/api/scenarios/{scenario_id}"): ("by_id", lambda a: {"json": {"name": "hijacked"}}),
    ("DELETE", "/api/scenarios/{scenario_id}"): ("by_id", lambda a: {}),
    ("POST", "/api/scenarios/{scenario_id}/adjustments"): ("by_id", lambda a: {"json": {"kind": "add", "name": "x", "amount_cents": 100, "direction": "out", "frequency": "monthly"}}),
    ("PATCH", "/api/adjustments/{adjustment_id}"): ("by_id", lambda a: {"json": {"kind": "remove", "target_recurring_id": a["item"]}}),
    ("DELETE", "/api/adjustments/{adjustment_id}"): ("by_id", lambda a: {}),
    ("GET", "/api/monthly"): own(params={"month": "2026-11"}),
    ("GET", "/api/until-paycheck"): own(params={"on": "2026-11-12"}),
    ("GET", "/api/daily-budget"): own(params={"on": "2026-11-12"}),
    ("POST", "/api/daily-spend"): ("by_id", lambda a: {"json": {"recurring_item_id": a["daily"], "date": "2026-11-12", "amount_cents": 100}}),
    ("PATCH", "/api/daily-spend/{spend_id}"): ("by_id", lambda a: {"json": {"amount_cents": 1}}),
    ("DELETE", "/api/daily-spend/{spend_id}"): ("by_id", lambda a: {}),
    ("POST", "/api/deferrals"): ("by_id", lambda a: {"json": {"recurring_item_id": a["item"], "month": "2026-12"}}),
    ("DELETE", "/api/deferrals/{deferral_id}"): ("by_id", lambda a: {}),
    ("GET", "/api/opening-balance/{month}"): own(),
    ("PUT", "/api/opening-balance/{month}"): own(json={"amount_cents": 1, "note": "Bob-note"}),
    ("DELETE", "/api/opening-balance/{month}"): own(),
    ("GET", "/api/trips"): own(),
    ("GET", "/api/trips/summary"): own(),
    ("PATCH", "/api/trips/{trip_id}"): ("admin", lambda a: {"json": {"excluded": True}}),
    ("POST", "/api/trips/{trip_id}/settle"): ("admin", lambda a: {"json": {"date": "2026-11-12", "amount_cents": 100}}),
    ("POST", "/api/trips/{trip_id}/unsettle"): ("admin", lambda a: {}),
    ("GET", "/api/linked-lists"): own(),
    ("GET", "/api/linked-lists/summary"): own(),
    ("POST", "/api/linked-lists"): ("admin", lambda a: {"json": {"list_id": a["list"]}}),
    ("PATCH", "/api/linked-lists/{list_id}"): ("admin", lambda a: {"json": {"excluded": True}}),
    ("DELETE", "/api/linked-lists/{list_id}"): ("admin", lambda a: {}),
    ("POST", "/api/linked-lists/{list_id}/settle"): ("admin", lambda a: {"json": {"date": "2026-11-12", "amount_cents": 100}}),
    ("POST", "/api/linked-lists/{list_id}/unsettle"): ("admin", lambda a: {}),
    ("GET", "/api/users"): ("admin", lambda a: {}),
    ("GET", "/api/users/suggestions"): ("admin", lambda a: {}),
    ("POST", "/api/users"): ("admin", lambda a: {"json": {"email": "friend@example.com"}}),
    ("PATCH", "/api/users/{user_id}"): ("admin", lambda a: {"json": {"status": "removed"}}),
    ("DELETE", "/api/users/{user_id}/data"): ("admin", lambda a: {}),
}
PATH_IDS = {
    "category_id": "cat", "person_id": "person", "item_id": "item", "txn_id": "txn", "fund_id": "fund", "scenario_id": "scenario",
    "adjustment_id": "adj", "spend_id": "spend", "deferral_id": "deferral", "month": "month", "trip_id": "trip", "list_id": "list",
}


def path_for(shown, ids, owner_user_id):
    path = shown
    for name, key_ in PATH_IDS.items():
        path = path.replace("{" + name + "}", str(ids[key_]))
    return path.replace("{user_id}", str(owner_user_id))


def test_every_route_is_examined_by_the_sweep():
    pages = {"/", "/budget.html", "/scenarios.html", "/settings.html", "/users.html"}
    listed = {(m, s) for m, s, _ in every_route() if s not in pages}
    assert listed == set(SPEC), f"routes not covered by the two-person sweep: {listed ^ set(SPEC)}"


def test_a_second_person_gets_nothing_of_the_owners_from_any_route_and_changes_nothing(two_people, client_for):
    t = two_people
    before_owner = snapshot(t["factory"], t["owner_id"])
    bob = client_for(BOB)
    problems = []
    for (method, shown), (kind, body) in SPEC.items():
        kw = body(t["owner"])
        resp = bob.request(method, path_for(shown, t["owner"], t["owner_id"]), **kw)
        if SECRET in resp.text:
            problems.append((method, shown, "showed the owner's data"))
        if kind == "by_id" and resp.status_code not in (400, 403, 404):
            problems.append((method, shown, f"answered {resp.status_code} to the owner's id"))
        if kind == "admin" and resp.status_code != 403:
            problems.append((method, shown, f"answered {resp.status_code} to a member"))
    assert not problems, problems
    assert snapshot(t["factory"], t["owner_id"]) == before_owner, "something of the owner's changed"


def test_the_pages_themselves_carry_no_data(two_people, client_for):
    bob = client_for(BOB)
    for page in PAGES:
        resp = bob.get(page)
        assert SECRET not in resp.text and SECRET not in bob.get("/app.js").text


def test_the_owner_can_use_every_route_that_is_refused_to_others(two_people, client_for):
    """Otherwise the checks above could be passing only because nothing works."""
    t = two_people
    owner = client_for(OWNER)
    worked = []
    for (method, shown), (kind, body) in SPEC.items():
        if method != "GET" or kind == "by_id":
            continue
        resp = owner.get(path_for(shown, t["owner"], t["owner_id"]), **body(t["owner"]))
        assert resp.status_code == 200, (shown, resp.status_code, resp.text[:200])
        worked.append(shown)
    assert len(worked) > 15
    found = [s for s in ("/api/recurring", "/api/people", "/api/transactions", "/api/funds", "/api/scenarios", "/api/categories")
             if SECRET in owner.get(s).text]
    assert len(found) >= 5


def test_lists_only_ever_hold_the_callers_own_rows(two_people, client_for):
    t = two_people
    bob = client_for(BOB)
    for path in ("/api/people", "/api/recurring", "/api/transactions", "/api/funds", "/api/scenarios"):
        rows = bob.get(path).json()
        assert rows and all("SECRET-BOB" in str(r) for r in rows), path
    assert [c["id"] for c in bob.get("/api/categories").json() if "SECRET" in c["name"]] == [t["bob"]["cat"]]
    # the aggregates add up Bob's rows alone: Bob's one $1,500 rent, none of the owner's
    assert bob.get("/api/recurring/summary").json()["item_count"] == 2
    assert bob.get("/api/funds/summary").json()["active_count"] == 1
    month = bob.get("/api/monthly", params={"month": "2026-11"}).text
    assert SECRET not in month and "SECRET-BOB" in month


def test_opening_balances_and_settings_are_each_persons_own(two_people, client_for):
    t = two_people
    bob = client_for(BOB)
    assert bob.put("/api/opening-balance/2026-11", json={"amount_cents": 111, "note": "mine"}).json()["override_cents"] == 111
    owner = client_for(OWNER)
    assert owner.get("/api/opening-balance/2026-11").json()["override_cents"] == 500000  # not Bob's, and not overwritten
    assert bob.delete("/api/opening-balance/2026-11").status_code == 200
    assert owner.get("/api/opening-balance/2026-11").json()["override_cents"] == 500000
    with working_as(t["factory"], t["owner_id"]) as db:
        assert db.query(models.AppSetting).count() == 1


# --- what one person names cannot reach another's rows ---------------------------------------------------------------------


def test_a_row_cannot_be_pointed_at_someone_elses_category_person_or_fund(two_people, client_for):
    t = two_people
    bob = client_for(BOB)
    owner_ids = t["owner"]
    attempts = [
        ("POST", "/api/recurring", {"name": "x", "amount_cents": 1, "direction": "out", "category_id": owner_ids["cat"]}),
        ("POST", "/api/recurring", {"name": "x", "amount_cents": 1, "direction": "out", "person_id": owner_ids["person"]}),
        ("POST", "/api/transactions", {"date": "2026-11-01", "description": "x", "amount_cents": 1, "direction": "out", "fund_id": owner_ids["fund"]}),
        ("POST", "/api/transactions", {"date": "2026-11-01", "description": "x", "amount_cents": 1, "direction": "out", "category_id": owner_ids["cat"]}),
        ("POST", "/api/funds", {"name": "x", "annual_amount_cents": 1200, "category_id": owner_ids["cat"]}),
        ("PATCH", f"/api/recurring/{t['bob']['item']}", {"category_id": owner_ids["cat"]}),
        ("PATCH", f"/api/transactions/{t['bob']['txn']}", {"person_id": owner_ids["person"]}),
        ("PATCH", f"/api/funds/{t['bob']['fund']}", {"person_id": owner_ids["person"]}),
        ("POST", f"/api/scenarios/{t['bob']['scenario']}/adjustments", {"kind": "remove", "target_recurring_id": owner_ids["item"]}),
        ("POST", f"/api/scenarios/{t['bob']['scenario']}/adjustments", {"kind": "remove", "target_fund_id": owner_ids["fund"]}),
        ("POST", f"/api/scenarios/{t['bob']['scenario']}/adjustments", {"kind": "remove", "target_transaction_id": owner_ids["txn"]}),
        ("POST", f"/api/scenarios/{t['bob']['scenario']}/adjustments", {"kind": "add", "name": "x", "amount_cents": 1, "direction": "out", "frequency": "monthly", "category_id": owner_ids["cat"]}),
        ("PATCH", f"/api/adjustments/{t['bob']['adj']}", {"kind": "remove", "target_recurring_id": owner_ids["item"]}),
    ]
    for method, path, body in attempts:
        resp = bob.request(method, path, json=body)
        assert resp.status_code == 400, (method, path, body, resp.status_code, resp.text)
    with working_as(t["factory"], t["bob_id"]) as db:
        assert db.query(models.RecurringItem).filter(models.RecurringItem.category_id == owner_ids["cat"]).count() == 0
        assert db.query(models.Transaction).filter(models.Transaction.fund_id == owner_ids["fund"]).count() == 0


def test_if_a_route_forgot_its_check_the_data_layer_still_refuses_with_a_clean_403(two_people, client_for, monkeypatch):
    """The friendly 400s above come from crud.check_references. With that switched off, the layer below must still refuse
    to link Bob's rows to the owner's, and the app must answer it as a refusal, not a crash."""
    t = two_people
    monkeypatch.setattr(crud, "check_references", lambda db, data: None)
    before_owner = snapshot(t["factory"], t["owner_id"])
    bob = client_for(BOB)
    owner_ids = t["owner"]
    for method, path, body in [
        ("POST", "/api/recurring", {"name": "x", "amount_cents": 1, "direction": "out", "category_id": owner_ids["cat"]}),
        ("PATCH", f"/api/transactions/{t['bob']['txn']}", {"person_id": owner_ids["person"]}),
        ("POST", f"/api/scenarios/{t['bob']['scenario']}/adjustments", {"kind": "remove", "target_recurring_id": owner_ids["item"]}),
    ]:
        resp = bob.request(method, path, json=body)
        assert resp.status_code == 403 and "isn't yours" in resp.text.replace("&#x27;", "'"), (method, path, resp.status_code, resp.text)
    assert snapshot(t["factory"], t["owner_id"]) == before_owner


def test_the_data_layer_refuses_what_a_route_forgot_to_check(two_people):
    """The routes check ids themselves, but if one ever forgot, the layer below refuses to link or write across people."""
    t = two_people
    with working_as(t["factory"], t["bob_id"]) as db:
        db.add(models.Transaction(date=date(2026, 11, 1), description="x", amount_cents=1, direction="out", category_id=t["owner"]["cat"]))
        with pytest.raises(owned.WrongOwner):
            db.commit()
        db.rollback()
        mine = db.query(models.RecurringItem).first()
        mine.person_id = t["owner"]["person"]
        with pytest.raises(owned.WrongOwner):
            db.commit()
        db.rollback()
        db.add(models.Person(name="x", color="#000", owner_id=t["owner_id"]))
        with pytest.raises(owned.WrongOwner):
            db.commit()
        db.rollback()
    with working_as(t["factory"], t["bob_id"]) as db:
        assert db.get(models.Category, t["owner"]["cat"]) is None  # by id, it simply is not there for Bob
    with owned.scope(t["bob_id"]), t["factory"]() as db:
        assert db.query(models.RecurringItem).filter(models.RecurringItem.id == t["owner"]["item"]).count() == 0


def test_the_database_code_never_runs_raw_sql_that_would_skip_the_filter():
    from pathlib import Path

    owned.assert_no_raw_sql([str(Path(__file__).resolve().parent.parent / "app")])


def test_names_and_references_are_unique_per_person_not_across_them(two_people, client_for):
    owner, bob = client_for(OWNER), client_for(BOB)
    assert owner.post("/api/categories", json={"name": "Shared name"}).status_code == 200
    assert bob.post("/api/categories", json={"name": "Shared name"}).status_code == 200
    assert owner.post("/api/people", json={"name": "Alex"}).status_code == 200
    assert bob.post("/api/people", json={"name": "Alex"}).status_code == 200
    item = {"name": "Loan", "amount_cents": 100, "direction": "out", "reference_id": "same-loan-id"}
    assert owner.post("/api/recurring", json=item).status_code == 200
    assert bob.post("/api/recurring", json=item).status_code == 200  # Bob is not told the owner has one
    assert bob.post("/api/recurring", json=item).status_code == 409  # but his own twin is caught


# --- trips and lists: the ADMINISTRATOR's other apps ---------------------------------------------------------------------


@pytest.fixture()
def other_apps(monkeypatch):
    """The real trips/lists fetch, with the other apps standing by to answer (and to say who asked)."""
    calls = []
    trips_service._cache.update(at=0.0, data=None, ok=True)
    lists_service.clear_cache()
    monkeypatch.setattr(trips_service, "fetch_trip_costs", REAL_FETCH_TRIPS)
    monkeypatch.setattr(lists_service, "fetch_list_costs", REAL_FETCH_LISTS)
    monkeypatch.setattr(config, "TRIPS_SERVICE_TOKEN", "trips-secret")
    monkeypatch.setattr(config, "LISTS_SERVICE_TOKEN", "lists-secret")
    monkeypatch.setattr(trips_service, "TRIPS_SERVICE_TOKEN", "trips-secret")
    monkeypatch.setattr(lists_service, "LISTS_SERVICE_TOKEN", "lists-secret")

    class Reply:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        if "cost-summary" in url and "/trips/" in url:
            return Reply([{"id": 5, "location": f"{SECRET}-Paris", "total_cost_cents": 240000, "start_date": "2027-05-01"}])
        return Reply([{"id": 9, "name": f"{SECRET}-Kitchen", "to_buy_cents": 50000, "bought_cents": 0, "excluded_count": 0, "unpriced_count": 0}])

    monkeypatch.setattr(trips_service.httpx, "get", fake_get)
    monkeypatch.setattr(lists_service.httpx, "get", fake_get)
    return calls


def test_the_administrator_sees_their_trips_and_lists(two_people, client_for, other_apps):
    owner = client_for(OWNER)
    assert SECRET in owner.get("/api/trips").text
    assert SECRET in owner.get("/api/linked-lists").text
    assert SECRET in owner.get("/api/scenarios/plannable").text
    assert other_apps  # the other apps really were asked


def test_nobody_else_ever_sees_or_triggers_them_not_even_from_the_cache(two_people, client_for, other_apps):
    owner, bob = client_for(OWNER), client_for(BOB)
    owner.get("/api/trips")  # warms the cache with the administrator's trips
    owner.get("/api/linked-lists")
    asked = len(other_apps)
    for path in ("/api/trips", "/api/trips/summary", "/api/linked-lists", "/api/linked-lists/summary", "/api/scenarios/plannable", "/api/monthly"):
        resp = bob.get(path, params={"month": "2026-11"} if path == "/api/monthly" else None)
        assert resp.status_code == 200 and SECRET not in resp.text, path
    assert bob.get("/api/trips").json()["upcoming"] == [] and bob.get("/api/trips/summary").json()["upcoming_count"] == 0
    assert bob.get("/api/linked-lists").json()["available"] == []
    assert len(other_apps) == asked, "the other apps were asked on a member's behalf"


def test_a_member_may_not_plan_settle_or_link_them(two_people, client_for, other_apps):
    t = two_people
    bob = client_for(BOB)
    assert bob.post(f"/api/trips/5/settle", json={"date": "2026-11-12"}).status_code == 403
    assert bob.post("/api/linked-lists", json={"list_id": 9}).status_code == 403
    planned = {"kind": "add", "add_kind": "planned", "name": "Paris", "link_kind": "trip", "link_id": 5, "date": "2027-05-01"}
    assert bob.post(f"/api/scenarios/{t['bob']['scenario']}/adjustments", json=planned).status_code == 403
    assert bob.patch(f"/api/adjustments/{t['bob']['adj']}", json=planned).status_code == 403
    assert client_for(OWNER).post(f"/api/scenarios/{t['owner']['scenario']}/adjustments", json=planned).status_code == 200


def test_outside_a_request_nothing_reaches_the_other_apps(world, other_apps):
    assert trips_service.fetch_trip_costs() == [] and lists_service.fetch_list_costs() == [] and not other_apps


# --- the Users page ------------------------------------------------------------------------------------------------------


def test_me_says_who_and_what_they_may_use(two_people, client_for):
    owner = client_for(OWNER).get("/api/me").json()
    assert owner["email"] == OWNER and owner["is_admin"] is True and owner["can_use"] == {"trips": True, "lists": True}
    assert owner["logout_url"] == FRONT + "/auth/logout"
    bob = client_for(BOB).get("/api/me").json()
    assert bob["is_admin"] is False and bob["can_use"] == {"trips": False, "lists": False}


def test_only_an_administrator_can_use_the_users_page_api(two_people, client_for):
    bob = client_for(BOB)
    assert bob.get("/api/users").status_code == 403
    assert bob.post("/api/users", json={"email": "friend@example.com"}).status_code == 403
    assert client_for(OWNER).get("/api/users").status_code == 200


def test_an_administrator_lets_someone_in_who_then_starts_empty_with_default_categories(two_people, client_for, monkeypatch):
    told = []
    monkeypatch.setattr(notify, "tell_let_in", lambda to, inviter: told.append((to, inviter)))
    owner = client_for(OWNER)
    assert client_for("newbie@example.com").get("/api/people").status_code == 403  # not yet
    resp = owner.post("/api/users", json={"email": " Newbie@Example.com "})
    assert resp.status_code == 200 and resp.json()["email"] == "newbie@example.com"
    assert told == [("newbie@example.com", OWNER)]
    newbie = client_for("newbie@example.com")
    assert newbie.get("/api/people").json() == [] and newbie.get("/api/recurring").json() == []
    assert len(newbie.get("/api/categories").json()) == len(DEFAULT_CATEGORIES)
    assert SECRET not in newbie.get("/api/monthly").text
    assert owner.post("/api/users", json={"email": "newbie@example.com"}).status_code == 200
    assert len(told) == 1  # someone who already has access is not told again


def test_what_an_administrator_cannot_do_on_the_users_page(two_people, client_for):
    t = two_people
    owner = client_for(OWNER)
    assert owner.post("/api/users", json={"email": "not-an-email"}).status_code == 400
    assert owner.post("/api/users", json={"email": crud.LEGACY_OWNER_EMAIL}).status_code == 400
    assert owner.patch(f"/api/users/{t['owner_id']}", json={"status": "removed"}).status_code == 409  # not themselves
    users = owner.get("/api/users").json()
    assert {u["email"] for u in users} == {OWNER, BOB} and crud.LEGACY_OWNER_EMAIL not in str(users)


def test_the_placeholder_for_the_old_data_is_never_listed_or_usable(production, client_for, make_user):
    make_user(OWNER)  # already has an account, so signing in does not adopt the placeholder
    with owned.unscoped(), production() as s:
        s.add(models.User(email=crud.LEGACY_OWNER_EMAIL))
        s.commit()
    users = client_for(OWNER).get("/api/users").json()
    assert crud.LEGACY_OWNER_EMAIL not in str(users)


def test_removing_someone_locks_them_out_but_keeps_their_data_until_deleted(two_people, client_for):
    t = two_people
    owner, bob = client_for(OWNER), client_for(BOB)
    assert owner.patch(f"/api/users/{t['bob_id']}", json={"status": "removed"}).json()["status"] == "removed"
    assert bob.get("/api/people").status_code == 403
    # deleting needs them removed first, and only ever deletes THEIR rows
    assert owner.patch(f"/api/users/{t['bob_id']}", json={"status": "active"}).json()["status"] == "active"
    assert owner.delete(f"/api/users/{t['bob_id']}/data").status_code == 409
    owner.patch(f"/api/users/{t['bob_id']}", json={"status": "removed"})
    before_owner = snapshot(t["factory"], t["owner_id"])
    deleted = owner.delete(f"/api/users/{t['bob_id']}/data").json()["deleted"]
    assert deleted["transactions"] == 1 and deleted["recurring_items"] == 2
    assert all(rows == [] for rows in snapshot(t["factory"], t["bob_id"]).values())
    assert snapshot(t["factory"], t["owner_id"]) == before_owner
    owner.patch(f"/api/users/{t['bob_id']}", json={"status": "active"})
    assert client_for(BOB).get("/api/people").json() == []  # restored, and empty


def test_an_administrators_account_is_made_on_first_sign_in_and_takes_over_the_existing_data(production, client_for):
    """The data that existed before accounts is parked on a placeholder; the first administrator to sign in takes it over
    (their email replaces the placeholder's) without a single row moving."""
    with owned.unscoped(), production() as s:
        legacy = models.User(email=crud.LEGACY_OWNER_EMAIL)
        s.add(legacy)
        s.commit()
        legacy_id = legacy.id
    with owned.scope(legacy_id), production() as s:
        s.add(models.Person(name=f"{SECRET}-old", color="#000"))
        s.commit()
    assert client_for(STRANGER).get("/api/people").status_code == 403  # a stranger takes nothing over
    owner = client_for(OWNER)
    assert [p["name"] for p in owner.get("/api/people").json()] == [f"{SECRET}-old"]
    with owned.unscoped(), production() as s:
        assert s.query(models.User).filter_by(id=legacy_id).one().email == OWNER
    assert owner.get("/api/categories").json() == []  # nothing new was seeded over the old data


def test_a_brand_new_administrator_with_no_old_data_gets_the_default_categories(production, client_for):
    assert len(client_for(OWNER).get("/api/categories").json()) == len(DEFAULT_CATEGORIES)


# --- the app's own pages and who is allowed to cause changes -----------------------------------------------------------------


def test_every_route_that_changes_something_refuses_a_request_from_another_app_or_site(two_people, client_for):
    """The sign-in cookie covers every subdomain and subdomains are the same site, so a page on another app could make the
    owner's browser change things here. The browser marks such a request (Sec-Fetch-Site), and every route that changes
    anything must refuse it even with a valid administrator cookie (shared_python.csrf)."""
    owner = client_for(OWNER)
    tried = 0
    for method, shown, _ in every_route():
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        for site in ("same-site", "cross-site"):
            resp = owner.request(method, concrete(shown), json={}, headers={"Sec-Fetch-Site": site, "Origin": "https://lists.example.org"})
            assert resp.status_code == 403 and "didn't come from this app" in resp.text, (method, shown, site, resp.status_code)
            tried += 1
    assert tried > 30


def test_the_owner_can_still_make_changes_from_the_apps_own_pages(two_people, client_for):
    owner = client_for(OWNER)
    resp = owner.post("/api/people", json={"name": "Ok"}, headers={"Sec-Fetch-Site": "same-origin", "Origin": "https://finances.example.org"})
    assert resp.status_code == 200


def test_locally_the_dev_user_is_the_administrator_with_an_account_of_their_own(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        assert client.get("/").status_code == 200 and client.get("/api/people").status_code == 200
        me = client.get("/api/me").json()
        assert me["email"] == config.DEV_USER_EMAIL and me["is_admin"] and me["logout_url"] is None
    finally:
        app.dependency_overrides.clear()


def fake_apps(tmp_path, monkeypatch, **emails_by_folder):
    """Other apps' databases next to this one, each with the given people (see shared_python.directory)."""
    for folder, (filename, emails) in emails_by_folder.items():
        (tmp_path / folder).mkdir(exist_ok=True)
        connection = sqlite3.connect(tmp_path / folder / filename)
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
        connection.executemany("INSERT INTO users (email) VALUES (?)", [(e,) for e in emails])
        connection.commit()
        connection.close()
    monkeypatch.setenv("PEOPLE_APPS_DIR", str(tmp_path))


def test_suggestions_are_everyone_from_any_app_minus_people_already_here(two_people, client_for, tmp_path, monkeypatch):
    fake_apps(
        tmp_path, monkeypatch,
        **{"lists": ("gifts.db", ["Zed@example.com", BOB]), "time-management": ("tasks.db", ["amy@example.com"])},
    )
    resp = client_for(OWNER).get("/api/users/suggestions")
    assert resp.status_code == 200
    # the owner and Bob already have accounts here, so they are not offered again; the rest are lowercased and sorted
    assert resp.json() == ["amy@example.com", "zed@example.com"]


def test_suggestions_say_who_uses_the_apps_so_only_an_administrator_gets_them(two_people, client_for, tmp_path, monkeypatch):
    fake_apps(tmp_path, monkeypatch, lists=("gifts.db", ["secret-person@example.com"]))
    resp = client_for(BOB).get("/api/users/suggestions")
    assert resp.status_code == 403 and "secret-person" not in resp.text
