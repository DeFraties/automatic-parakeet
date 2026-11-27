from datetime import date

from sqlalchemy import select

from app.models import Property
from ingest.config import SourceConfig, load_sources
from ingest.http import PoliteClient
from ingest.pipeline import IngestDeps, run_source
from ingest.sources.example_html import ExampleHtml
from tests.ingest_fakes import EverythingUrban, FakeFx, FakeImageCheck


def run_example(db, fixture_site, tmp_path, **settings):
    sleeps = []
    client = PoliteClient("BallparkBot/test", tmp_path, sleep=sleeps.append, jitter=lambda: 0)
    cfg = SourceConfig(key="example_html", enabled=True, delay_seconds=5, max_records_per_run=50,
                       settings={"base_url": fixture_site.url + "/",
                                 "image_hosts": ["images.example.test"], **settings})  # fmt: skip
    check = FakeImageCheck()
    run = run_source(db, ExampleHtml(), cfg, IngestDeps(client, FakeFx(), EverythingUrban(), check))
    client.close()
    props = {p.source_ref: p for p in db.execute(select(Property)).scalars()}
    return run, props, sleeps, check


def test_example_plugin_end_to_end(db, fixture_site, tmp_path):
    run, props, sleeps, check = run_example(db, fixture_site, tmp_path)

    assert run.status == "ok", run.message
    assert run.inserted == 2
    assert run.details["reasons"] == {"robots_disallowed": 1, "plugin_skipped": 1}  # private + POR
    assert "/private/members_only.html" not in fixture_site.paths()
    assert fixture_site.paths()[0] == "/robots.txt"
    assert sleeps and min(sleeps) >= 4.5  # per-domain page delay applied

    # --- JSON listing ------------------------------------------------------------------------
    pt = props["EX-1001"]
    assert (pt.price_local, pt.currency, pt.country_code, pt.city) == (
        340_000,
        "EUR",
        "PT",
        "Lisbon",
    )
    assert (pt.area_m2, pt.bedrooms, pt.bathrooms, pt.year_built) == (85.0, 2, 1, 1965)
    assert (pt.lat, pt.lng, pt.location_precision) == (38.71391, -9.1394, "exact")
    assert pt.property_type == "apartment" and pt.setting == "urban"
    assert pt.price_type == "asking" and pt.price_date == date.today()
    assert pt.listing_url.endswith("/example_listing.html")
    assert len(pt.images) == 8
    assert pt.images[0].url == "https://images.example.test/ex-1001/1-1600.jpg"
    assert [i.kind for i in pt.images].count("floorplan") == 1
    assert pt.images[4].kind == "floorplan"  # stored in listing order
    assert pt.images_status == "ok"

    # --- HTML fallback listing ---------------------------------------------------------------
    hr = props["EX-2002"]
    assert (hr.price_local, hr.currency) == (200_013, "EUR")  # kn 1.507.000 at 7.53450
    assert hr.area_m2 == 150.0 and hr.property_type == "house" and hr.year_built == 1998
    assert (hr.lat, hr.location_precision) == (43.5081, "approximate")
    assert [i.url.rsplit("/", 1)[1] for i in hr.images] == [
        "a_1600.jpg",
        "b_1600.jpg",
        "c_800.jpg",
        "plan_800.png",
    ]  # largest published, in order
    assert hr.images[3].kind == "floorplan"

    # photos are only checked, never downloaded through our fixture server
    assert len(check.calls) == 12
    assert not any("/ex-" in p for p in fixture_site.paths())

    # Nothing but facts + photo URLs made it into the database.
    dump = " ".join(str(v) for p in props.values() for v in vars(p).values())
    for forbidden in ("river views", "Maria", "+351", "maria@example.com", "Rua de", "Ivan",
                      "1100-000", "Quiet street"):  # fmt: skip
        assert forbidden not in dump


def test_shipped_sources_yaml():
    cfg = load_sources()
    assert set(cfg) == {"example_html"}
    ex = cfg["example_html"]
    assert not ex.enabled and ex.delay_seconds == 5
    assert ex.settings["image_hosts"] == ["images.example.test"]
    assert ex.settings["allow_price_range_midpoint"] is False
