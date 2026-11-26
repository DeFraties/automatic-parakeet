from datetime import date

from sqlalchemy import select

from app.models import Property
from ingest.config import SourceConfig, load_sources
from ingest.http import PoliteClient
from ingest.pipeline import IngestDeps, run_source
from ingest.sources.example_html import ExampleHtml
from tests.ingest_fakes import FakeFx, NoRaster


def test_example_plugin_end_to_end(db, fixture_site, tmp_path):
    sleeps = []
    client = PoliteClient("BallparkBot/test", tmp_path, sleep=sleeps.append, jitter=lambda: 0)
    cfg = SourceConfig(
        key="example_html",
        enabled=True,
        delay_seconds=5,
        max_records_per_run=50,
        settings={"base_url": fixture_site.url + "/"},
    )
    run = run_source(db, ExampleHtml(), cfg, IngestDeps(client, FakeFx(), NoRaster()))
    client.close()

    assert run.status == "ok", run.message
    assert run.inserted == 2
    assert run.details["reasons"] == {"robots_disallowed": 1}
    assert "/private/members_only.html" not in fixture_site.paths()
    assert fixture_site.paths()[0] == "/robots.txt"
    assert sleeps and min(sleeps) >= 4.5  # per-domain delay applied between requests

    props = {p.source_ref: p for p in db.execute(select(Property)).scalars()}
    pt = props["EX-1001"]
    assert (pt.price_local, pt.currency, pt.country_code) == (340_000, "EUR", "PT")
    assert (pt.area_m2, pt.bedrooms, pt.bathrooms, pt.year_built) == (85.0, 2, 1, 1965)
    assert pt.property_type == "apartment" and pt.location_precision == "exact"
    assert pt.price_date == date(2025, 10, 1)
    assert pt.listing_url.endswith("/example_listing.html")

    hr = props["EX-2002"]
    assert (hr.price_local, hr.currency) == (200_013, "EUR")  # kn 1.507.000 at 7.53450
    assert hr.area_m2 == 150.0 and hr.property_type == "house"
    assert hr.location_precision == "street"

    # Nothing but facts made it into the database.
    dump = " ".join(str(v) for p in props.values() for v in vars(p).values())
    for forbidden in (
        "photos/",
        "river views",
        "Maria",
        "+351",
        "maria@example.com",
        "Rua de",
        "Ivan",
    ):
        assert forbidden not in dump


def test_shipped_sources_yaml():
    cfg = load_sources()
    assert cfg["uk_price_paid"].enabled and cfg["uk_price_paid"].max_records_per_run == 2000
    assert cfg["uk_price_paid"].settings["filters"] == {
        "min_year": 2022,
        "property_types": ["D", "S", "T", "F"],
    }
    assert not cfg["example_html"].enabled and cfg["example_html"].delay_seconds == 5
