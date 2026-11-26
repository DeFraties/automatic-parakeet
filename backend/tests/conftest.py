import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ballpark-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["RATE_LIMIT_GAMES_PER_HOUR"] = "0"
os.environ["RATE_LIMIT_GUESSES_PER_HOUR"] = "0"
os.environ["MIN_POOL_PER_OPTION"] = "50"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core import fx  # noqa: E402
from app.core.db import Base, get_db, make_engine  # noqa: E402
from app.core.security import limiter  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        yield s


@pytest.fixture
def client(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    limiter.reset()
    fx.clear_cache()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    fx.clear_cache()


@pytest.fixture
def seeded(db):
    from app.seed import seed

    seed(db)
    return db
