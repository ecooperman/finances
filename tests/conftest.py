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
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base  # noqa: E402
from app.services import trips as trips_service  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    os.unlink(_db_file.name)


@pytest.fixture()
def db():
    # StaticPool + one shared in-memory DB so a TestClient request (which
    # runs the handler on another thread) sees the same tables.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _no_live_trip_fetch(monkeypatch):
    """Isolate the suite from the trip-planning app: by default no trips.
    Use the `set_trips` fixture (tests/test_trips.py) to supply data.
    """
    trips_service._cache["data"] = None
    trips_service._cache["at"] = 0.0
    monkeypatch.setattr(trips_service, "fetch_trip_costs", lambda: [])
