import random
from collections import Counter
from datetime import date, timedelta

import pytest

from app.core.selection import (
    Candidate,
    PoolTooSmall,
    load_candidates,
    pick_rounds,
    price_quintiles,
)
from app.models import Blocklist, Property, Source

TODAY = date(2026, 6, 1)


def make_pool(countries=("FR", "GB", "JP", "US", "BR", "AU"), cities=4, per_city=3):
    pool, i = [], 0
    for cc in countries:
        for ci in range(cities):
            for k in range(per_city):
                i += 1
                setting = "urban" if (ci + k) % 2 else "suburban"
                price = 20_000 * (1.6 ** (i % 13))
                pool.append(Candidate(f"p{i:04d}", cc, f"{cc}-city{ci}", setting, price))
    return pool


@pytest.mark.parametrize("seed", range(30))
def test_world_rules(seed):
    pool = make_pool()
    picks = pick_rounds(
        pool, rng=random.Random(seed), min_pool_per_country=1, setting_filter="suburban,urban"
    )
    assert len(picks) == 5
    assert len({p.id for p in picks}) == 5
    assert len({(p.country_code, p.city) for p in picks}) == 5  # no repeated city
    assert max(Counter(p.country_code for p in picks).values()) <= 2  # <= 2 per country
    q = price_quintiles(pool)
    assert len({q[p.id] for p in picks}) >= 3  # price-band spread
    s = Counter(p.setting for p in picks)
    assert s["urban"] >= 2 and s["suburban"] >= 2


def test_deterministic_with_seeded_rng():
    pool = make_pool()
    a = pick_rounds(pool, rng=random.Random("2026-06-01"))
    b = pick_rounds(list(reversed(pool)), rng=random.Random("2026-06-01"))
    assert [p.id for p in a] == [p.id for p in b]


def test_country_weighting_is_equal_per_country():
    # One giant country and five small ones: the giant shouldn't dominate.
    pool = make_pool(countries=("GB",), cities=40, per_city=5) + make_pool(
        countries=("FR", "JP", "US", "BR", "AU"), cities=5, per_city=2
    )
    pool = [
        Candidate(f"{c.country_code}-{c.id}", c.country_code, c.city, c.setting, c.price_usd)
        for c in pool
    ]
    counts = Counter()
    for s in range(200):
        for p in pick_rounds(pool, rng=random.Random(s), min_pool_per_country=1):
            counts[p.country_code] += 1
    share_gb = counts["GB"] / sum(counts.values())
    assert share_gb < 0.3  # ~1/6 expected; would be ~0.8 if picking uniformly by property


def test_country_threshold_used_when_enough_countries():
    pool = make_pool(countries=("GB", "FR", "JP"), cities=10, per_city=6) + make_pool(
        countries=("US",), cities=2, per_city=1
    )
    pool = [
        Candidate(f"{c.country_code}-{c.id}", c.country_code, c.city, c.setting, c.price_usd)
        for c in pool
    ]
    for s in range(50):
        picks = pick_rounds(pool, rng=random.Random(s), min_pool_per_country=50)
        assert "US" not in {p.country_code for p in picks}


def test_single_country_ignores_country_cap_but_keeps_city_rule():
    pool = make_pool(countries=("JP",), cities=6, per_city=3)
    for s in range(20):
        picks = pick_rounds(pool, rng=random.Random(s), where_scope="country")
        assert {p.country_code for p in picks} == {"JP"}
        assert len({p.city for p in picks}) == 5


def test_single_country_relaxes_city_rule_with_few_cities():
    pool = make_pool(countries=("TW",), cities=2, per_city=4)
    picks = pick_rounds(pool, rng=random.Random(1), where_scope="country")
    assert len(picks) == 5


def test_pool_too_small():
    with pytest.raises(PoolTooSmall):
        pick_rounds(make_pool(countries=("FR",), cities=1, per_city=4), rng=random.Random(0))


def test_urban_only_filter_returns_only_requested(db):
    _make_db_pool(db)
    cands = load_candidates(db, today=TODAY, max_age_years=5, setting_filter="urban")
    assert cands and all(c.setting == "urban" for c in cands)


def _prop(src, ref, **kw):
    base = dict(
        source_id=src.id,
        source_ref=ref,
        price_type="sale_record",
        price_local=300_000,
        currency="EUR",
        price_usd=324_000,
        fx_rate_to_usd=1.08,
        price_date=TODAY - timedelta(days=30),
        country_code="FR",
        city="Lyon",
        lat=45.76,
        lng=4.83,
        location_precision="exact",
        setting="urban",
        property_type="house",
        sv_status="ok",
        is_active=True,
    )
    base.update(kw)
    return Property(**base)


def _make_db_pool(db):
    src = Source(key="t", display_name="Test")
    db.add(src)
    db.flush()
    props = {
        "good": _prop(src, "good"),
        "good_sub": _prop(src, "good_sub", setting="suburban"),
        "street": _prop(src, "street", location_precision="street"),
        "inactive": _prop(src, "inactive", is_active=False),
        "no_sv": _prop(src, "no_sv", sv_status="none"),
        "unchecked": _prop(src, "unchecked", sv_status="unchecked"),
        "district": _prop(src, "district", location_precision="district"),
        "cheap": _prop(src, "cheap", price_usd=4_999),
        "pricey": _prop(src, "pricey", price_usd=100_000_001),
        "old": _prop(src, "old", price_date=TODAY - timedelta(days=365 * 5 + 5)),
        "rural": _prop(src, "rural", setting="rural"),
        "unknown": _prop(src, "unknown", setting="unknown"),
        "foreign": _prop(src, "foreign", country_code="DE"),
        "blocked": _prop(src, "blocked"),
    }
    db.add_all(props.values())
    db.add(Blocklist(source_id=src.id, source_ref="blocked"))
    db.commit()
    return {k: v.id for k, v in props.items()}


def test_eligibility_filters(db):
    ids = _make_db_pool(db)
    got = {
        c.id
        for c in load_candidates(db, today=TODAY, max_age_years=5, setting_filter="suburban,urban")
    }
    # Imageless homes are playable by default (illustrated card), whatever their image checks say.
    assert got == {ids[k] for k in ("good", "good_sub", "street", "no_sv", "unchecked")}


def test_eligibility_requires_an_image_when_imageless_disabled(db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_imageless_rounds", False)
    ids = _make_db_pool(db)
    p = {k: db.get(Property, v) for k, v in ids.items()}
    p["good"].pano_id = "PANO"  # sv ok + pano
    p["good_sub"].image_url = "https://img.example/1.jpg"  # listing photo
    p["street"].sv_status = "none"
    p["street"].mly_status, p["street"].mly_image_id = "ok", "123"  # Mapillary
    p["unchecked"].mly_status = "ok"  # ok but no id -> no image
    db.commit()
    got = {
        c.id: c.has_image
        for c in load_candidates(db, today=TODAY, max_age_years=5, setting_filter="suburban,urban")
    }
    assert got == {ids["good"]: True, ids["good_sub"]: True, ids["street"]: True}


def test_prefers_homes_with_images():
    pool = [
        Candidate(c.id, c.country_code, c.city, c.setting, c.price_usd, has_image=i % 4 == 0)
        for i, c in enumerate(make_pool())
    ]
    picks = [
        p
        for s in range(30)
        for p in pick_rounds(pool, rng=random.Random(s), setting_filter="suburban,urban")
    ]
    assert sum(p.has_image for p in picks) >= 120  # of 150 picks; only 25% of the pool has one


def test_scope_filters(db):
    _make_db_pool(db)
    assert (
        load_candidates(
            db,
            today=TODAY,
            max_age_years=5,
            setting_filter="suburban,urban",
            where_scope="country",
            where_value="JP",
        )
        == []
    )
    assert (
        len(
            load_candidates(
                db,
                today=TODAY,
                max_age_years=5,
                setting_filter="suburban,urban",
                where_scope="region",
                where_value="europe",
            )
        )
        == 5
    )


@pytest.mark.parametrize("seed", range(20))
def test_three_settings_get_one_of_each(seed):
    pool = [
        Candidate(c.id, c.country_code, c.city, ("urban", "suburban", "rural")[i % 3], c.price_usd)
        for i, c in enumerate(make_pool())
    ]
    picks = pick_rounds(
        pool, rng=random.Random(seed), min_pool_per_country=1, setting_filter="rural,suburban,urban"
    )
    assert {p.setting for p in picks} == {"urban", "suburban", "rural"}


def test_encode_settings():
    from app.core.selection import decode_settings, encode_settings

    assert encode_settings(["urban", "rural", "urban"]) == "rural,urban"
    assert decode_settings("rural,urban") == ("rural", "urban")
    for bad in ([], ["beach"]):
        with pytest.raises(ValueError):
            encode_settings(bad)
