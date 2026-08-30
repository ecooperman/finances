import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services import trips as trips_service


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
