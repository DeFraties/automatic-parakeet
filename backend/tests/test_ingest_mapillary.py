from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Property, Source
from ingest.cli import main
from ingest.mapillary import MapillaryChecker, MapillaryCheckError, angle_diff, best_image
from tests.test_ingest_cli import cli_env  # noqa: F401

HOUSE = (53.8000, -1.5000)


def img(id_, dlat_m, dlng_m, angle, pano=False):
    lat = HOUSE[0] + dlat_m / 111_320
    lng = HOUSE[1] + dlng_m / (111_320 * 0.5878)  # cos(53.8°)
    return {
        "id": id_,
        "computed_geometry": {"type": "Point", "coordinates": [lng, lat]},
        "computed_compass_angle": angle,
        "is_pano": pano,
    }


def test_angle_diff():
    assert angle_diff(350, 10) == 20 and angle_diff(10, 350) == 20 and angle_diff(90, 270) == 180


def test_picks_close_image_facing_the_house():
    images = [
        img("behind", 0, -20, 270),  # 20 m west, looking west (away)
        img("facing", 0, -25, 90),  # 25 m west, looking east (at the house)
        img("far", 0, -200, 90),  # too far
        img("pano", 0, -5, 90, pano=True),  # panoramas skipped
    ]
    assert best_image(images, *HOUSE) == "facing"


def test_closer_wins_when_both_face():
    images = [img("a", 30, 0, 180), img("b", 10, 0, 185)]
    assert best_image(images, *HOUSE) == "b"


def test_nothing_suitable():
    assert best_image([img("away", 0, -20, 270)], *HOUSE) is None
    assert best_image([], *HOUSE) is None


def _prop(db, n=2):
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
                lat=HOUSE[0],
                lng=HOUSE[1] + i,
                location_precision="exact",
                property_type="house",
            )
        )
    db.commit()


def checker(handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    return MapillaryChecker(
        "MLY|t", transport=httpx.MockTransport(wrapped), sleep=lambda s: None
    ), calls


def test_run_marks_ok_and_none(db):
    _prop(db, 2)

    def handler(request):
        west = float(request.url.params["bbox"].split(",")[0])
        data = [img("123", 0, -25, 90)] if west < 0 else []
        return httpx.Response(200, json={"data": data})

    c, calls = checker(handler)
    assert c.run(db) == {"ok": 1, "none": 1}
    got = {
        p.source_ref: (p.mly_status, p.mly_image_id) for p in db.execute(select(Property)).scalars()
    }
    assert got == {"r0": ("ok", "123"), "r1": ("none", None)}
    assert calls[0].headers["Authorization"] == "OAuth MLY|t"
    assert "computed_compass_angle" in calls[0].url.params["fields"]


def test_errors_stop_without_marking(db):
    _prop(db, 1)
    c, _ = checker(lambda r: httpx.Response(401, json={"error": "bad token"}))
    with pytest.raises(MapillaryCheckError):
        c.run(db)
    assert db.execute(select(Property.mly_status)).scalar_one() == "unchecked"


def test_cli_requires_token(cli_env, capsys):  # noqa: F811
    assert main(["mapillary-check"]) == 1
    assert "MAPILLARY_TOKEN" in capsys.readouterr().err


def test_strip_photos(cli_env, capsys):  # noqa: F811
    with SessionLocal() as db:
        _prop(db, 2)
        for p in db.execute(select(Property)).scalars():
            p.image_url = "https://x/1.jpg"
        db.commit()
    assert main(["strip-photos", "--source", "t"]) == 0
    assert "Removed 2 photo links" in capsys.readouterr().out
    with SessionLocal() as db:
        assert {p.image_url for p in db.execute(select(Property)).scalars()} == {None}
        assert all(p.is_active for p in db.execute(select(Property)).scalars())
    assert main(["strip-photos", "--source", "nope"]) == 2
