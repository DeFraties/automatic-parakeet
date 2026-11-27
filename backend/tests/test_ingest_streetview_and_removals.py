from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Blocklist, Property, RemovalRequest, Source
from ingest.cli import main
from ingest.streetview import StreetViewChecker, StreetViewCheckError
from tests.test_ingest_cli import cli_env  # noqa: F401  (fixture)


def checker(responses):
    calls = []

    def handler(request):
        calls.append(request)
        status = responses(request)
        body = {"status": status}
        if status == "OK":
            body |= {"pano_id": "PANO-1", "location": {"lat": 1, "lng": 2}, "date": "2024-05"}
        return httpx.Response(200, json=body)

    return StreetViewChecker(
        "KEY", transport=httpx.MockTransport(handler), sleep=lambda s: None
    ), calls


def _props(db, n=3, precision="exact"):
    src = Source(key="t", display_name="T")
    db.add(src)
    db.flush()
    for i in range(n):
        db.add(
            Property(
                source_id=src.id,
                source_ref=f"r{i}",
                price_type="sale_record",
                price_local=1,
                currency="GBP",
                price_usd=1,
                fx_rate_to_usd=1,
                price_date=date(2025, 1, 1),
                country_code="GB",
                city="Leeds",
                lat=53.8 + i / 100,
                lng=-1.5,
                location_precision=precision,
                property_type="house",
                sv_status="unchecked",
            )
        )
    db.commit()


def test_marks_ok_and_none_and_stores_only_pano(db):
    _props(db, 3)
    clf, calls = checker(
        lambda r: "OK" if r.url.params["location"].startswith("53.80") else "ZERO_RESULTS"
    )
    assert clf.run(db) == {"ok": 1, "none": 2}
    props = db.execute(select(Property).order_by(Property.source_ref)).scalars().all()
    assert [(p.sv_status, p.pano_id) for p in props] == [
        ("ok", "PANO-1"),
        ("none", None),
        ("none", None),
    ]
    q = calls[0].url.params
    assert q["radius"] == "50" and q["source"] == "outdoor" and q["key"] == "KEY"


def test_skips_district_precision(db):
    _props(db, 2, precision="district")
    clf, calls = checker(lambda r: "OK")
    assert clf.run(db) == {"ok": 0, "none": 0} and calls == []


@pytest.mark.parametrize("status", ["REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST"])
def test_google_errors_stop_without_marking(db, status):
    _props(db, 2)
    clf, _ = checker(lambda r: status)
    with pytest.raises(StreetViewCheckError):
        clf.run(db)
    assert {p.sv_status for p in db.execute(select(Property)).scalars()} == {"unchecked"}


def test_requires_key():
    with pytest.raises(StreetViewCheckError):
        StreetViewChecker("")


def test_removal_cli_flow(cli_env, capsys):  # noqa: F811
    with SessionLocal() as db:
        _props(db, 2)
        db.add(RemovalRequest(email="o@example.com", reference="r0", message="mine"))
        db.commit()
        pid = db.execute(select(Property.id).where(Property.source_ref == "r0")).scalar_one()

    assert main(["removals"]) == 0
    assert "o@example.com" in capsys.readouterr().out
    assert main(["remove", "--property-id", pid, "--request", "1"]) == 0
    with SessionLocal() as db:
        assert db.get(Property, pid).is_active is False
        assert db.execute(select(Blocklist.source_ref)).scalars().all() == ["r0"]
        assert db.get(RemovalRequest, 1).status == "done"
    capsys.readouterr()
    assert main(["removals"]) == 0
    assert "No pending" in capsys.readouterr().out
    assert main(["remove", "--property-id", "nope"]) == 2


def test_deactivate_source(cli_env, capsys):  # noqa: F811
    with SessionLocal() as db:
        _props(db, 3)
    assert main(["deactivate", "--source", "t"]) == 0
    with SessionLocal() as db:
        assert {p.is_active for p in db.execute(select(Property)).scalars()} == {False}
        assert db.execute(select(Source.enabled)).scalar_one() is False
    assert main(["deactivate", "--source", "zzz"]) == 2


def test_streetview_check_cli_needs_key(cli_env, capsys):  # noqa: F811
    assert main(["streetview-check"]) == 1
    assert "GOOGLE_MAPS_API_KEY" in capsys.readouterr().err
