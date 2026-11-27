from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core import daily
from app.core.db import SessionLocal
from app.models import (
    Blocklist,
    DailyChallenge,
    GameRound,
    PhotoReport,
    Property,
    PropertyImage,
    Source,
    utcnow,
)
from ingest.cli import main
from ingest.http import PoliteClient
from ingest.images import run_images_check, verify_property
from ingest.models import NormalizedImage, NormalizedListing
from ingest.refresh import purge_gone_listings, run_refresh
from ingest.sources.base import SourcePlugin
from tests.ingest_fakes import FakeImageCheck
from tests.test_ingest_cli import cli_env  # noqa: F401

HOST = "img.test"


def _prop(db, src, ref, *, seen_days_ago=20, price_type="asking", n=3, is_active=True, **kw):
    p = Property(source_id=src.id, source_ref=ref, listing_url=f"https://listings.test/{ref}",
                 price_type=price_type, price_local=300_000, currency="EUR", price_usd=324_000,
                 fx_rate_to_usd=1.08, price_date=date.today(), country_code="PT", city="Lisbon",
                 lat=38.7, lng=-9.1, location_precision="exact", setting="urban",
                 property_type="house", images_status="ok", is_active=is_active,
                 last_seen_at=utcnow() - timedelta(days=seen_days_ago), **kw)  # fmt: skip
    p.images = [PropertyImage(position=i, url=f"https://{HOST}/{ref}/{i}.jpg", status="ok")
                for i in range(n)]  # fmt: skip
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def src(db):
    s = Source(key="fake", display_name="Fake", image_hosts=[HOST], enabled=True)
    db.add(s)
    db.flush()
    return s


class RefreshPlugin(SourcePlugin):
    key = "fake"
    display_name = "Fake"
    homepage = "https://listings.test"
    price_type = "asking"
    country_codes = ["PT"]
    image_hosts = [HOST]

    def __init__(self, live):
        super().__init__()
        self.live = live  # ref -> number of photos (None = delisted)

    def discover(self, client, settings):
        return []

    def fetch_and_parse(self, client, ref):
        key = ref.rsplit("/", 1)[1]
        n = self.live.get(key)
        if n is None:
            return None
        return NormalizedListing(
            source_ref=key, listing_url=ref, price_type="asking", price_local=300_000,
            currency="EUR", price_date=date.today(), country_code="PT", city="Lisbon",
            property_type="house",
            images=[NormalizedImage(f"https://{HOST}/{key}/v2-{i}.jpg") for i in range(n)],
        )  # fmt: skip


class FakeClient:
    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = []

    def get(self, url, use_cache=True):
        self.calls.append((url, use_cache))
        from ingest.http import FetchResult

        return FetchResult(url, self.statuses.get(url.rsplit("/", 1)[1], 200), "<html/>")


def test_refresh_live_gone_and_delisted(db, src):
    _prop(db, src, "live")
    _prop(db, src, "gone404")
    _prop(db, src, "delisted")
    _prop(db, src, "recent", seen_days_ago=2)
    db.commit()
    client = FakeClient({"gone404": 404})
    plugin = RefreshPlugin({"live": 4, "gone404": 4, "delisted": None})
    c = run_refresh(db, {"fake": plugin}, client, FakeImageCheck(), older_than_days=14, limit=50)
    assert (c["checked"], c["live"], c["gone"]) == (3, 1, 2)
    assert all(not use_cache for _, use_cache in client.calls)  # always a fresh fetch
    p = {x.source_ref: x for x in db.execute(select(Property)).scalars()}
    assert p["live"].is_active and p["live"].last_seen_at > utcnow() - timedelta(minutes=1)
    assert [i.url.rsplit("/", 1)[1] for i in p["live"].images] == [f"v2-{i}.jpg" for i in range(4)]
    assert p["live"].images_status == "ok"
    assert not p["gone404"].is_active and not p["delisted"].is_active
    assert p["recent"].is_active  # not due yet


def test_purge_deletes_long_gone_asking_listings_with_photos(db, src):
    old = _prop(db, src, "old", seen_days_ago=40, is_active=False)
    played = _prop(db, src, "played", seen_days_ago=40, is_active=False)
    sold = _prop(db, src, "sold", seen_days_ago=40, is_active=False, price_type="sale_record")
    young = _prop(db, src, "young", seen_days_ago=10, is_active=False)
    from app.models import Game

    g = Game(mode="classic")
    db.add(g)
    db.flush()
    db.add(GameRound(game_id=g.id, round_no=1, property_id=played.id))
    db.commit()
    ids = (old.id, played.id, sold.id, young.id)
    assert purge_gone_listings(db) == 2
    db.expire_all()
    assert db.get(Property, ids[0]) is None  # deleted outright
    assert db.get(Property, ids[1]) is not None and db.get(Property, ids[1]).images == []
    assert len(db.get(Property, ids[2]).images) == 3  # sale records aren't purged
    assert len(db.get(Property, ids[3]).images) == 3  # not gone long enough


def test_verify_property_hosts_and_two_ok_rule(db, src):
    p = _prop(db, src, "a", n=3)
    p.images[2].url = "https://evil.test/x.jpg"
    p.images[1].url = f"https://{HOST}/a/broken.jpg"
    assert verify_property(p, FakeImageCheck(), [HOST]) == "broken"
    assert [i.status for i in p.images] == ["ok", "broken", "broken"]
    assert p.images_checked_at is not None


def test_images_check_picks_unchecked_and_stale(db, src, tmp_path, monkeypatch):
    _prop(db, src, "fresh", images_checked_at=utcnow())
    _prop(db, src, "stale", images_checked_at=utcnow() - timedelta(days=30))
    new = _prop(db, src, "new")
    new.images_status = "unchecked"
    db.commit()
    checked = []
    monkeypatch.setattr(PoliteClient, "check_image",
                        lambda self, url, delay=1: checked.append(url) or True)  # fmt: skip
    client = PoliteClient("t", tmp_path)
    c = run_images_check(db, client, limit=50, stale_days=14)
    client.close()
    assert c["ok"] == 2
    assert not any("/fresh/" in u for u in checked)
    assert any("/stale/" in u for u in checked) and any("/new/" in u for u in checked)


# ---------------------------------------------------------------- Daily re-check -------------
def test_daily_replaces_picks_whose_photos_fail(seeded):
    today = daily.utc_today()
    first = daily.generate_ids(seeded, today)
    bad = set(first[:2])
    calls = []

    def verify(db, p):
        calls.append(p.id)
        return p.id not in bad

    ids = daily.generate_ids(seeded, today, verify=verify)
    assert len(ids) == 5 and not bad & set(ids)
    assert set(first[:2]) <= set(calls)


def test_daily_prefers_recently_verified(seeded):
    from app.models import Property as P

    for p in seeded.query(P).all():
        p.images_checked_at = utcnow() - timedelta(days=10)
    fresh = [p for p in seeded.query(P).filter(P.setting.in_(("urban", "rural"))).all()][::3]
    for p in fresh:
        p.images_checked_at = utcnow() - timedelta(hours=3)
    seeded.commit()
    ids = daily.generate_ids(seeded, daily.utc_today())
    assert set(ids) <= {p.id for p in fresh}


def test_daily_challenge_saved_via_api_uses_verifier(client, seeded, monkeypatch):
    seen = []
    monkeypatch.setattr(daily, "photo_verifier", lambda db, p: seen.append(p.id) or True)
    assert client.post("/api/daily/start", json={}, headers={"X-Device-Id": "d"}).status_code == 201
    row = seeded.execute(select(DailyChallenge)).scalar_one()
    assert set(row.property_ids) <= set(seen)


# ---------------------------------------------------------------- CLI: reports/removals -----
def test_reports_and_remove_cli(cli_env, capsys):  # noqa: F811
    with SessionLocal() as db:
        s = Source(key="fake", display_name="Fake", image_hosts=[HOST], enabled=True)
        db.add(s)
        db.flush()
        p = _prop(db, s, "a", n=3)
        db.add(PhotoReport(property_id=p.id, position=1, reason="price_visible"))
        db.add(PhotoReport(property_id=p.id, position=0, reason="person"))
        db.commit()
        pid = p.id
    assert main(["reports"]) == 0
    out = capsys.readouterr().out
    assert "price_visible" in out and "person" in out and "listings.test/a" in out
    assert main(["reports", "--resolve", "1", "--action", "drop-photo"]) == 0
    with SessionLocal() as db:
        assert [i.position for i in db.get(Property, pid).images] == [0, 2]
        assert db.get(Property, pid).images_status == "ok"
    assert main(["reports", "--resolve", "2", "--action", "dismiss"]) == 0
    capsys.readouterr()
    assert main(["reports"]) == 0
    assert "No open photo reports" in capsys.readouterr().out
    assert main(["remove", "--property-id", pid]) == 0
    with SessionLocal() as db:
        prop = db.get(Property, pid)
        assert not prop.is_active and prop.images == []  # photo URLs deleted too
        assert db.execute(select(Blocklist.source_ref)).scalars().all() == ["a"]
