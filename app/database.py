import os

from shared_python import owned
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# DATABASE_URL lets the tests, migrations (see migrations/env.py) or a scratch copy
# of the data use another database; the default is the app's own file.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./finances.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Every person's data is private to them: the filter below hooks every session so a query that forgets to filter by
# owner still only sees the signed-in person's rows (see shared_python/owned.py and app/access.py).
owned.install()
