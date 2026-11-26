import logging
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Blocklist, IngestRun, Property
from ingest.config import SourceConfig
from ingest.http import PoliteClient, SourceBlocked
from ingest.models import NormalizedListing
from ingest.pipeline import IngestDeps, run_source
from ingest.sources.base import SourcePlugin
from tests.ingest_fakes import FakeFx, NoRaster


def L(ref, **kw):  # noqa: N802
    base = dict(
        source_ref=ref,
        price_type="asking",
        price_local=300_000,
        currency="EUR",
        price_date=date(2025, 1, 1),
        country_code="PT",
        city="Lisbon",
        lat=38.7,
        lng=-9.1,
        location_precision="exact",
        property_type="apartment",
        area_m2=85.0,
    )
    base.update(kw)
    return NormalizedListing(**base)


class FakePlugin(SourcePlugin):
    key = "fake"
    display_name = "Fake source"
    homepage = "https://fake.test"
    price_type = "asking"
    country_codes = ["PT"]

    def __init__(self, items, block_at=None, key=None):
        super().__init__()
        self.items = items
        self.block_at = block_at
        if key:
            self.key = key
        self.fetched = []

    def discover(self, client, settings):
        yield from self.items

    def fetch_and_parse(self, client, ref):
        self.fetched.append(ref)
        if ref == self.block_at:
            raise SourceBlocked("HTTP 429")
        item = self.items[ref]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def deps(tmp_path):
    client = PoliteClient("BallparkBot/test", tmp_path)
    yield IngestDeps(client, FakeFx(missing={"JPY"}), NoRaster())
    client.close()


def cfg(**kw):
    return SourceConfig(key="fake", enabled=True, max_records_per_run=kw.pop("max", 100), **kw)


def props(db):
    return {p.source_ref: p for p in db.execute(select(Property)).scalars()}


def test_inserts_valid_records_and_records_run(db, deps):
    items = {"a": L("a"), "b": L("b", price_local=500_000, city="Porto")}
    run = run_source(db, FakePlugin(items), cfg(), deps)
    assert (run.status, run.inserted, run.rejected) == ("ok", 2, 0)
    p = props(db)["a"]
    assert p.price_usd == pytest.approx(324_000) and p.fx_rate_to_usd == 1.08
    assert p.sv_status == "unchecked" and p.is_active
    assert p.setting == "unknown"  # no raster available
    assert db.execute(select(IngestRun)).scalar_one().inserted == 2


def test_drops_non_launch_countries(db, deps, caplog):
    caplog.set_level(logging.INFO)
    items = {
        "de": L("de", country_code="DE"),
        "pt": L("pt"),
        "us": L("us", country_code="us", currency="USD"),
    }
    run = run_source(db, FakePlugin(items), cfg(), deps)
    assert run.dropped_country == 1 and run.inserted == 2
    assert run.details["dropped_countries"] == {"DE": 1}
    assert set(props(db)) == {"pt", "us"}
    assert "non-launch-country" in caplog.text


def test_hrk_converted_to_eur(db, deps):
    run = run_source(
        db,
        FakePlugin(
            {
                "hr": L(
                    "hr",
                    country_code="HR",
                    currency="HRK",
                    price_local=1_507_000,
                    price_date=date(2022, 6, 1),
                )
            }
        ),
        cfg(),
        deps,
    )
    assert run.inserted == 1
    p = props(db)["hr"]
    assert (p.price_local, p.currency) == (200_013, "EUR")
    assert ("EUR", date(2022, 6, 1)) in deps.fx.calls


def test_missing_fx_rate_skips_record(db, deps, caplog):
    run = run_source(
        db, FakePlugin({"jp": L("jp", country_code="JP", currency="JPY")}), cfg(), deps
    )
    assert run.inserted == 0 and run.details["reasons"] == {"no_fx_rate": 1}
    assert "no FX rate" in caplog.text


def test_validation_rejections_are_counted(db, deps):
    items = {"cheap": L("cheap", price_local=1000), "tiny": L("tiny", area_m2=5), "ok": L("ok")}
    run = run_source(db, FakePlugin(items), cfg(), deps)
    assert run.rejected == 2 and run.inserted == 1
    assert run.details["reasons"]["price_out_of_range"] == 1
    assert run.details["reasons"]["area_out_of_range"] == 1


def test_dedupes_on_source_ref_and_resets_streetview_when_moved(db, deps):
    run_source(db, FakePlugin({"a": L("a")}), cfg(), deps)
    p = props(db)["a"]
    p.sv_status, p.pano_id = "ok", "PANO"
    db.commit()
    run = run_source(db, FakePlugin({"a": L("a", price_local=310_000)}), cfg(), deps)
    assert (run.inserted, run.updated) == (0, 1)
    p = props(db)["a"]
    assert p.price_local == 310_000 and p.sv_status == "ok"  # same place: keep pano
    run_source(db, FakePlugin({"a": L("a", lat=38.8)}), cfg(), deps)
    p = props(db)["a"]
    assert p.sv_status == "unchecked" and p.pano_id is None
    assert len(props(db)) == 1


def test_blocklisted_refs_never_ingested(db, deps):
    run_source(db, FakePlugin({}), cfg(), deps)  # creates the source row
    from app.models import Source

    src = db.execute(select(Source).where(Source.key == "fake")).scalar_one()
    db.add(Blocklist(source_id=src.id, source_ref="gone"))
    db.commit()
    plugin = FakePlugin({"gone": L("gone"), "ok": L("ok")})
    run = run_source(db, plugin, cfg(), deps)
    assert "gone" not in plugin.fetched and set(props(db)) == {"ok"}
    assert run.details["reasons"]["blocklisted"] == 1


def test_flags_cross_source_duplicates(db, deps):
    run_source(db, FakePlugin({"a": L("a")}), cfg(), deps)
    near = L("x", lat=38.70005, price_local=303_000)  # ~5.5 m away, 1% pricier
    far = L("y", lat=38.7005, price_local=300_000)  # ~55 m away
    run = run_source(
        db,
        FakePlugin({"x": near, "y": far}, key="other"),
        SourceConfig(key="other", enabled=True),
        deps,
    )
    assert run.possible_duplicates == 1
    assert len(run.details["possible_duplicates"]) == 1


def test_block_stops_run_and_keeps_earlier_records(db, deps):
    items = {"a": L("a"), "b": L("b"), "c": L("c")}
    plugin = FakePlugin(items, block_at="b")
    run = run_source(db, plugin, cfg(), deps)
    assert run.status == "blocked" and "BLOCKED" in run.message
    assert plugin.fetched == ["a", "b"]  # stopped immediately, no retry
    assert set(props(db)) == {"a"}
    assert run.inserted == 1


def test_parse_errors_dont_stop_the_run(db, deps):
    run = run_source(db, FakePlugin({"bad": ValueError("boom"), "ok": L("ok")}), cfg(), deps)
    assert run.status == "ok" and run.inserted == 1
    assert run.details["reasons"]["parse_error"] == 1


def test_respects_max_records(db, deps):
    items = {str(i): L(str(i)) for i in range(10)}
    run = run_source(db, FakePlugin(items), cfg(max=3), deps)
    assert run.fetched == 3 and run.inserted == 3


def test_source_row_carries_licence_and_enabled_flag(db, deps):
    from app.models import Source
    from ingest.pipeline import ensure_source
    from ingest.sources.uk_price_paid import UkPricePaid

    src = ensure_source(db, UkPricePaid(), SourceConfig(key="uk_price_paid", enabled=True))
    assert src.enabled and "Open Government Licence v3.0" in src.license_note
    assert str(date.today().year) in src.license_note and "{year}" not in src.license_note
    assert db.execute(select(Source.key)).scalars().all() == ["uk_price_paid"]
