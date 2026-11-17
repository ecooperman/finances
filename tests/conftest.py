"""DATABASE_URL points the whole suite at a throwaway SQLite file *before* the
app is imported (app/database.py reads it when it loads), so no test can reach
the real finances.db even by accident. The `db` fixture below still gives each
test its own fresh in-memory database; see tests/test_database_url.py for the
checks that this holds and that the real migrations build the same schema."""
import os
import tempfile

_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from shared_python import owned  # noqa: E402
from shared_python import settings as shared_settings  # noqa: E402

from app import access, config, integrations, models  # noqa: E402
from app.database import Base  # noqa: E402
from app.services import linked_lists as linked_lists_service  # noqa: E402
from app.services import trips as trips_service  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    os.unlink(_db_file.name)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A fresh database for one test, in a file of its own (a request runs on another thread, so it needs real connections:
    several threads sharing one in-memory connection corrupt each other). The app's own account lookup (app/access.py) is
    pointed at it too. Returns the session factory."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(access, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def db(world):
    """A session working as the dev user (an administrator locally, and who every local request is treated as): the app
    keeps every person's data private, so even a test's own database calls belong to someone. Use the `make_user` and
    `as_user` fixtures (tests/test_accounts.py) to bring in a second person."""
    with owned.unscoped(), world() as session:
        dev = models.User(email=config.DEV_USER_EMAIL)
        session.add(dev)
        session.commit()
        dev_id = dev.id
    session = world()
    with owned.scope(dev_id):
        yield session
    session.close()


@pytest.fixture(autouse=True)
def _no_live_trip_fetch(monkeypatch):
    """Isolate the suite from the trip-planning app: by default no trips.
    Use the `set_trips` fixture (tests/test_trips.py) to supply data.
    """
    trips_service._cache["data"] = None
    trips_service._cache["at"] = 0.0
    trips_service._cache["ok"] = True
    monkeypatch.setattr(trips_service, "fetch_trip_costs", lambda: [])


@pytest.fixture(autouse=True)
def _no_live_list_fetch(monkeypatch):
    """Same for the lists app: by default it is reachable and reports no lists. Use the `set_lists`
    fixture (tests/test_linked_lists.py) to supply data, or None for "unreachable"."""
    linked_lists_service.clear_cache()
    monkeypatch.setattr(linked_lists_service, "fetch_list_costs", lambda: [])


@pytest.fixture(autouse=True)
def _local_sign_in(monkeypatch):
    """Whatever sign-in settings the developer's shell has, tests start local, with the dev user as the administrator."""
    for name in (
        "CF_TEAM_DOMAIN", "CF_ACCESS_AUD", "OIDC_ISSUER", "OIDC_JWKS_URL", "OIDC_AUDIENCE", "OIDC_COOKIE", "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET", "OIDC_COOKIE_DOMAIN", "OIDC_RETURN_HOSTS", "OIDC_LOGIN_URL", "OIDC_LOGOUT_RETURN_PATH",
    ):
        monkeypatch.setattr(shared_settings, name, None)
    monkeypatch.setattr(shared_settings, "ENV", "local")


@pytest.fixture()
def as_administrator():
    """For a test that calls the trips/lists services directly: pretend an administrator's request is running (the
    services read nothing for anyone else, see app/integrations.py)."""
    token = integrations.set_allowed(True)
    yield
    integrations.reset(token)
