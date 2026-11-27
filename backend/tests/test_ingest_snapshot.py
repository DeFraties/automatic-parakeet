from datetime import date

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Blocklist, Property, Source
from ingest import snapshot
from ingest.cli import main
from tests.test_ingest_cli import cli_env  # noqa: F401


def _seed(db, key="uk", n=3):
    src = Source(key=key, display_name="UK", license_note="Contains HM Land Registry data")
    db.add(src)
    db.flush()
    for i in range(n):
        db.add(
            Property(
                source_id=src.id,
                source_ref=f"r{i}",
                price_type="sale_record",
                price_local=300_000 + i,
                currency="GBP",
                price_usd=381_000,
                fx_rate_to_usd=1.27,
                price_date=date(2025, 1, 1 + i),
                country_code="GB",
                city="Leeds",
                region="West Yorkshire",
                lat=53.8 + i / 1000,
                lng=-1.55,
                location_precision="exact",
                setting="urban",
                setting_class_raw=30,
                property_type="house",
                sv_status="unchecked",
                mly_status="ok",
                mly_image_id=f"m{i}",
                is_active=i != 2,
            )
        )
    db.commit()
    return src


def test_roundtrip_into_empty_db(engine, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base, make_engine

    S = sessionmaker(bind=engine, expire_on_commit=False)
    with S() as db:
        _seed(db)
        assert (
            snapshot.export(db, "uk", tmp_path / "s.jsonl.gz", notice="OGL") == 2
        )  # inactive excluded

    other = make_engine(f"sqlite:///{tmp_path / 'other.db'}")
    Base.metadata.create_all(other)
    with sessionmaker(bind=other)() as db2:
        assert snapshot.load(db2, tmp_path / "s.jsonl.gz")["inserted"] == 2
        props = {p.source_ref: p for p in db2.execute(select(Property)).scalars()}
        p = props["r1"]
        assert (p.price_local, p.price_date, p.setting, p.mly_image_id, p.region) == (
            300_001,
            date(2025, 1, 2),
            "urban",
            "m1",
            "West Yorkshire",
        )
        assert db2.execute(select(Source.license_note)).scalar_one().startswith("Contains HM")
        # idempotent
        assert snapshot.load(db2, tmp_path / "s.jsonl.gz") == {
            "inserted": 0,
            "updated": 2,
            "skipped_blocklisted": 0,
            "skipped_inactive": 0,
        }


def test_load_respects_blocklist_and_removals(db, tmp_path):
    src = _seed(db)
    snapshot.export(db, "uk", tmp_path / "s.jsonl.gz")
    db.add(Blocklist(source_id=src.id, source_ref="r0"))
    for p in db.execute(select(Property)).scalars():
        if p.source_ref == "r1":
            p.is_active = False
    db.commit()
    c = snapshot.load(db, tmp_path / "s.jsonl.gz")
    assert c == {"inserted": 0, "updated": 0, "skipped_blocklisted": 1, "skipped_inactive": 1}
    assert (
        db.execute(select(Property.is_active).where(Property.source_ref == "r1")).scalar() is False
    )


def test_cli(cli_env, capsys):  # noqa: F811
    f = cli_env / "snap.jsonl.gz"
    with SessionLocal() as db:
        _seed(db)
    assert main(["snapshot", "export", "uk", str(f), "--playable-only"]) == 0
    assert "Exported 2" in capsys.readouterr().out
    with SessionLocal() as db:
        db.query(Property).delete()
        db.commit()
    assert main(["snapshot", "load", str(f)]) == 0
    assert "2 new" in capsys.readouterr().out
