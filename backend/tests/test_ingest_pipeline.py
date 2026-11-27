import logging
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import Blocklist, IngestRun, Property, PropertyImage, Source
from ingest.config import SourceConfig
from ingest.http import PoliteClient, SourceBlocked
from ingest.models import NormalizedImage, NormalizedListing
from ingest.pipeline import IngestDeps, ensure_source, run_source
from ingest.sources.base import SourcePlugin
from tests.ingest_fakes import EverythingUrban, FakeFx, FakeImageCheck

HOST = "images.example.test"


def photos(ref, n=3, broken=()):
    return [
        NormalizedImage(url=f"https://{HOST}/{ref}/{i}{'-broken' if i in broken else ''}.jpg",
                        width=1600, height=1067)
        for i in range(n)
    ]  # fmt: skip


def L(ref, **kw):  # noqa: N802
    base = dict(source_ref=ref, listing_url=f"https://listings.test/{ref}", price_type="asking",
                price_local=300_000, currency="EUR", price_date=date.today() - timedelta(days=3),
                country_code="PT", city="Lisbon", lat=38.7, lng=-9.1,
                location_precision="exact", property_type="apartment", area_m2=85.0,
                images=photos(ref))  # fmt: skip
    base.update(kw)
    return NormalizedListing(**base)


class FakePlugin(SourcePlugin):
    key = "fake"
    display_name = "Fake Listings"
    homepage = "https://listings.test"
    price_type = "asking"
    country_codes = ["PT"]
    image_hosts = [HOST]

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
    yield IngestDeps(
        client, FakeFx(missing={"JPY"}), EverythingUrban(), image_check=FakeImageCheck()
    )
    client.close()


def cfg(**kw):
    return SourceConfig(key=kw.pop("key", "fake"), enabled=True,
                        max_records_per_run=kw.pop("max", 100), **kw)  # fmt: skip


def props(db):
    return {p.source_ref: p for p in db.execute(select(Property)).scalars()}


def test_inserts_listing_with_ordered_photos_and_run_row(db, deps):
    run = run_source(db, FakePlugin({"a": L("a", images=photos("a", 4))}), cfg(), deps)
    assert (run.status, run.inserted, run.rejected) == ("ok", 1, 0)
    p = props(db)["a"]
    assert p.price_usd == pytest.approx(324_000) and p.fx_rate_to_usd == 1.08
    assert p.listing_url == "https://listings.test/a"
    assert [i.url for i in p.images] == [f"https://{HOST}/a/{i}.jpg" for i in range(4)]
    assert [i.position for i in p.images] == [0, 1, 2, 3]
    assert p.images_status == "ok" and p.images_checked_at is not None
    assert p.setting == "urban" and p.last_seen_at is not None
    assert db.execute(select(IngestRun)).scalar_one().details["images_ok"] == 1
    assert db.execute(select(Source.image_hosts)).scalar_one() == [HOST]


def test_photos_verified_and_status_follows_two_ok_rule(db, deps):
    items = {"one_ok": L("one_ok", images=photos("one_ok", 3, broken=(1, 2))),
             "two_ok": L("two_ok", images=photos("two_ok", 3, broken=(2,)))}  # fmt: skip
    run_source(db, FakePlugin(items), cfg(), deps)
    p = props(db)
    assert p["one_ok"].images_status == "broken"
    assert p["two_ok"].images_status == "ok"
    assert [i.status for i in p["two_ok"].images] == ["ok", "ok", "broken"]


def test_only_max_photos_stored(db, deps):
    run_source(db, FakePlugin({"a": L("a", images=photos("a", 14))}), cfg(), deps)
    assert len(props(db)["a"].images) == 10


def test_unchanged_photos_not_rechecked(db, deps):
    run_source(db, FakePlugin({"a": L("a")}), cfg(), deps)
    n = len(deps.image_check.calls)
    run_source(db, FakePlugin({"a": L("a")}), cfg(), deps)
    assert len(deps.image_check.calls) == n
    run_source(db, FakePlugin({"a": L("a", images=photos("a", 5))}), cfg(), deps)
    assert len(props(db)["a"].images) == 5 and len(deps.image_check.calls) > n


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"images": photos("x", 1)}, "too_few_photos"),
        ({"images": [NormalizedImage("https://evil.test/1.jpg"), *photos("x", 2)]},
         "image_host_not_allowed"),
        ({"images": [NormalizedImage(f"http://{HOST}/1.jpg"), *photos("x", 2)]},
         "image_host_not_allowed"),
        ({"is_rental": True}, "rental"),
        ({"price_local": 4_000, "area_m2": 80}, "price_out_of_range"),
        ({"price_local": 6_000, "area_m2": 80}, "looks_like_rent"),
        ({"listing_url": ""}, "missing_listing_url"),
        ({"lat": 38.7, "lng": None}, "bad_coordinates"),
    ],
)  # fmt: skip
def test_validation_rejections(db, deps, kw, reason):
    run = run_source(db, FakePlugin({"x": L("x", **kw)}), cfg(), deps)
    assert run.rejected == 1 and reason in run.details["reasons"]
    assert props(db) == {}


def test_listing_without_coordinates_is_unknown(db, deps):
    run_source(db, FakePlugin({"a": L("a", lat=None, lng=None, location_precision="exact")}),
               cfg(), deps)  # fmt: skip
    p = props(db)["a"]
    assert (p.lat, p.lng, p.location_precision, p.setting) == (None, None, None, "unknown")


def test_drops_non_launch_countries(db, deps, caplog):
    caplog.set_level(logging.INFO)
    items = {"de": L("de", country_code="DE"), "pt": L("pt")}
    run = run_source(db, FakePlugin(items), cfg(), deps)
    assert run.dropped_country == 1 and run.inserted == 1
    assert run.details["dropped_countries"] == {"DE": 1}
    assert "non-launch-country" in caplog.text


def test_hrk_converted_to_eur(db, deps):
    run_source(db, FakePlugin({"hr": L("hr", country_code="HR", currency="HRK",
                                       price_local=1_507_000)}), cfg(), deps)  # fmt: skip
    p = props(db)["hr"]
    assert (p.price_local, p.currency) == (200_013, "EUR")


def test_missing_fx_rate_skips_record(db, deps, caplog):
    run = run_source(db, FakePlugin({"jp": L("jp", country_code="JP", currency="JPY")}),
                     cfg(), deps)  # fmt: skip
    assert run.inserted == 0 and run.details["reasons"] == {"no_fx_rate": 1}
    assert "no FX rate" in caplog.text


def test_asking_price_keeps_first_scraped_date(db, deps):
    first = date.today() - timedelta(days=20)
    run_source(db, FakePlugin({"a": L("a", price_date=first)}), cfg(), deps)
    run_source(db, FakePlugin({"a": L("a", price_date=date.today())}), cfg(), deps)
    assert props(db)["a"].price_date == first
    run_source(db, FakePlugin({"a": L("a", price_local=280_000, price_date=date.today())}),
               cfg(), deps)  # fmt: skip
    assert props(db)["a"].price_date == date.today()  # new price, new date


def test_blocklisted_refs_never_ingested(db, deps):
    run_source(db, FakePlugin({}), cfg(), deps)
    src = db.execute(select(Source).where(Source.key == "fake")).scalar_one()
    db.add(Blocklist(source_id=src.id, source_ref="gone"))
    db.commit()
    plugin = FakePlugin({"gone": L("gone"), "ok": L("ok")})
    run = run_source(db, plugin, cfg(), deps)
    assert "gone" not in plugin.fetched and set(props(db)) == {"ok"}
    assert run.details["reasons"]["blocklisted"] == 1


def test_cross_source_duplicate_kept_out_of_pool(db, deps):
    run_source(db, FakePlugin({"a": L("a")}), cfg(), deps)
    near = L("x", lat=38.70005, price_local=303_000)  # ~5.5 m away, 1% pricier
    far = L("y", lat=38.7005)  # ~55 m away
    run = run_source(db, FakePlugin({"x": near, "y": far}, key="other"), cfg(key="other"), deps)
    assert run.possible_duplicates == 1
    p = props(db)
    assert p["a"].is_active and not p["x"].is_active and p["y"].is_active


def test_block_stops_run_and_keeps_earlier_records(db, deps):
    plugin = FakePlugin({"a": L("a"), "b": L("b"), "c": L("c")}, block_at="b")
    run = run_source(db, plugin, cfg(), deps)
    assert run.status == "blocked" and "BLOCKED" in run.message
    assert plugin.fetched == ["a", "b"]
    assert set(props(db)) == {"a"}


def test_parse_errors_dont_stop_the_run(db, deps):
    run = run_source(db, FakePlugin({"bad": ValueError("boom"), "ok": L("ok")}), cfg(), deps)
    assert run.status == "ok" and run.inserted == 1
    assert run.details["reasons"]["parse_error"] == 1


def test_respects_max_records(db, deps):
    run = run_source(db, FakePlugin({str(i): L(str(i)) for i in range(10)}), cfg(max=3), deps)
    assert run.fetched == 3 and run.inserted == 3


def test_source_row_carries_image_hosts_and_enabled_flag(db):
    src = ensure_source(
        db,
        FakePlugin({}),
        SourceConfig(key="fake", enabled=True, settings={"image_hosts": ["cdn.x.test"]}),
    )
    assert src.enabled and src.image_hosts == ["cdn.x.test"]


def test_property_images_never_store_bytes():
    cols = {c.name for c in PropertyImage.__table__.columns}
    assert cols == {"property_id", "position", "url", "width", "height", "kind", "status"}
