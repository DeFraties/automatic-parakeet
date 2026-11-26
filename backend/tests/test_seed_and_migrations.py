from collections import Counter
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from app.core.countries import COUNTRY_CODES
from app.core.db import Base
from app.models import Property
from app.seed import DEMO_PROPERTIES, seed


def test_seed_covers_all_countries(db):
    assert seed(db) == len(DEMO_PROPERTIES) == 51
    props = db.execute(select(Property)).scalars().all()
    per_country = Counter(p.country_code for p in props)
    assert set(per_country) == COUNTRY_CODES
    assert min(per_country.values()) >= 3
    assert {p.setting for p in props} == {"urban", "suburban", "rural"}
    assert {p.price_type for p in props} == {"sale_record", "asking"}
    assert all(p.source.display_name.startswith("DEMO") for p in props)


def test_seed_is_idempotent(db):
    seed(db)
    seed(db)
    assert len(db.execute(select(Property)).scalars().all()) == 51


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(url))
    tables = set(insp.get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}
