"""The suite runs against a throwaway database (DATABASE_URL, set in conftest.py),
and the real migrations build the schema the models describe."""
import os
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app import database

ROOT = Path(__file__).resolve().parent.parent


def test_the_suite_never_points_at_the_real_database():
    url = os.environ["DATABASE_URL"]
    assert database.DATABASE_URL == url
    assert str(database.engine.url) == url
    assert not url.endswith("/finances.db") and "./finances.db" not in url


def test_migrations_build_what_the_models_describe(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    os.environ["DATABASE_URL"] = url  # migrations/env.py reads it
    try:
        command.upgrade(cfg, "head")
    finally:
        os.environ["DATABASE_URL"] = str(database.engine.url)
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), database.Base.metadata)
    assert diff == [], f"the models and the migrations disagree: {diff}"
