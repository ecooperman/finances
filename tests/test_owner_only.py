"""The whole app is private to its administrators. It is the household budget and has no accounts of its own, so
this is the only thing between the internet and the data once Cloudflare Access is no longer in front of it. The
sweep calls EVERY route with no sign-in and as someone who is not an administrator, and also checks that no
response carries a real piece of data; a route added later cannot slip past (the gate is middleware around the
whole app) and this fails if one ever does."""
import re
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from shared_python import auth, settings

from app import config, models
from app.deps import get_db
from app.main import app

ISSUER = "https://login.example.com"
CLIENT = "client-123"
FRONT = "https://dashboard.example.org"
PAGES = ["/", "/budget.html", "/scenarios.html", "/settings.html"]
MARKER = "SECRET-MORTGAGE-XYZ"  # a recognisable piece of data: it must never reach anyone but an administrator


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def production(monkeypatch, key, db):
    db.add(models.RecurringItem(name=MARKER, direction="out", frequency="monthly", amount_cents=123456, active=True))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"owner@example.com"})
    monkeypatch.setattr(settings, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", CLIENT)
    monkeypatch.setattr(settings, "OIDC_LOGIN_URL", FRONT + "/auth/login")
    monkeypatch.setattr(auth, "_oidc_signing_key", lambda _t: key.public_key())
    yield TestClient(app, base_url="https://finances.example.org", follow_redirects=False)
    app.dependency_overrides.clear()


def session(key, email):
    return jwt.encode(
        {"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 300, "email": email, "email_verified": True}, key, algorithm="RS256"
    )


def every_route():
    for shown, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.upper() not in ("HEAD", "OPTIONS"):
                yield method.upper(), shown, re.sub(r"\{[^}]+\}", "1", shown)


def call(client, method, path):
    body = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
    return client.request(method, path, **body)


def test_there_are_routes_to_sweep():
    assert len(list(every_route())) > 40  # guards against the sweep silently covering nothing


def test_nobody_signed_out_gets_anything_from_any_route(production):
    answered = []
    for method, shown, path in every_route():
        resp = call(production, method, path)
        if resp.status_code not in (401, 302) or MARKER in resp.text:
            answered.append((method, shown, resp.status_code))
    for page in PAGES + ["/app.js", "/budget.js", "/scenarios.js", "/settings.js", "/common.js", "/nav.js", "/style.css", "/version.js", "/nope"]:
        resp = production.get(page)
        if resp.status_code != 302:
            answered.append(("GET", page, resp.status_code))
    assert not answered, f"answered with no sign-in: {answered}"


def test_nobody_signed_in_as_a_stranger_gets_anything_either(production, key):
    production.cookies.set("oidc_session", session(key, "stranger@example.com"))
    answered = []
    for method, shown, path in every_route():
        resp = call(production, method, path)
        if resp.status_code != 403 or MARKER in resp.text:
            answered.append((method, shown, resp.status_code))
    assert not answered, f"answered a signed-in stranger: {answered}"
    assert production.get("/").status_code == 403 and production.get("/app.js").status_code == 403


def test_the_administrator_gets_the_app_and_the_data(production, key):
    production.cookies.set("oidc_session", session(key, "owner@example.com"))
    for page in PAGES:
        assert production.get(page).status_code == 200
    found = [path for method, _, path in every_route() if method == "GET" and MARKER in production.get(path).text]
    assert found, "the administrator should be able to read the data (otherwise the checks above prove nothing)"


def test_a_signed_out_visitor_to_a_page_is_sent_to_sign_in_and_back(production):
    resp = production.get("/budget.html")
    assert resp.status_code == 302 and resp.headers["location"].startswith(FRONT + "/auth/login?next=")


def test_nothing_is_public_not_even_a_manifest_or_icons(production):
    for path in ("/manifest.json", "/icons/icon-192.png", "/sw.js", "/robots.txt"):
        assert production.get(path).status_code == 302


def test_a_service_token_for_another_app_opens_nothing(production, monkeypatch):
    monkeypatch.setattr(config, "TRIPS_SERVICE_TOKEN", "trips-secret")
    monkeypatch.setattr(config, "LISTS_SERVICE_TOKEN", "lists-secret")
    for token in ("trips-secret", "lists-secret"):
        for path in ("/api/people", "/api/recurring", "/api/balance"):
            assert production.get(path, headers={"X-Service-Token": token}).status_code == 401


def test_without_an_administrator_configured_in_production_nobody_gets_in(production, key, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    production.cookies.set("oidc_session", session(key, "owner@example.com"))
    assert production.get("/api/people").status_code == 503


def test_an_expired_session_is_treated_as_signed_out(production, key):
    production.cookies.set("oidc_session", session(key, "owner@example.com").replace(".", "x.", 1))
    assert production.get("/api/people").status_code == 401


def test_locally_the_dev_user_is_the_administrator(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        assert client.get("/").status_code == 200 and client.get("/api/people").status_code == 200
    finally:
        app.dependency_overrides.clear()


# --- who is signed in, for the header's Log out ----------------------------------------------------------------------


def test_me_says_who_is_signed_in_and_where_log_out_goes(production, key):
    production.cookies.set("oidc_session", session(key, "Owner@Example.com"))
    assert production.get("/api/me").json() == {"email": "owner@example.com", "is_admin": True, "logout_url": FRONT + "/auth/logout"}


def test_me_is_refused_to_anyone_who_is_not_signed_in_or_not_an_administrator(production, key):
    assert production.get("/api/me").status_code == 401
    production.cookies.set("oidc_session", session(key, "stranger@example.com"))
    assert production.get("/api/me").status_code == 403


def test_locally_me_is_the_dev_user_with_no_front_door(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        me = TestClient(app).get("/api/me").json()
        assert me["email"] == config.DEV_USER_EMAIL and me["logout_url"] is None
    finally:
        app.dependency_overrides.clear()
