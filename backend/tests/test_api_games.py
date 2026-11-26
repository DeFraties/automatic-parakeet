import json
from collections import Counter

import pytest

from app.core import security
from app.models import Property

PRICE_KEYS = {"price_local", "price_usd", "listing_url", "fx_rate_to_usd", "guess_usd", "fx_hint"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _prop_for(db, game_id, round_no):
    from app.models import GameRound

    r = db.get(GameRound, (game_id, round_no))
    db.refresh(r)
    return db.get(Property, r.property_id)


def _new(client, **body):
    res = client.post("/api/games", json=body, headers={"X-Device-Id": "test-device"})
    assert res.status_code == 201, res.text
    return res.json()


def _guess(client, gid, n, amount, currency="USD"):
    return client.post(
        f"/api/games/{gid}/rounds/{n}/guess", json={"amount": amount, "currency": currency}
    )


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_defaults_are_normal_world_classic(client, seeded):
    g = _new(client)
    assert g["difficulty"] == "normal"
    assert g["where_scope"] == "world" and g["where_value"] is None
    assert g["mode"] == "classic"
    assert g["rounds_total"] == 5
    r = g["round"]
    assert r["round_no"] == 1
    assert r["guess_currency"] == "USD"
    assert r["slider"] == {"min": 5_000, "max": 50_000_000}


def test_round_payload_never_contains_price(client, seeded):
    g = _new(client)
    gid, payload = g["game_id"], g["round"]
    for n in range(1, 6):
        assert not (set(_keys(payload)) & PRICE_KEYS)
        p = _prop_for(seeded, gid, n)
        assert str(p.price_local) not in json.dumps(payload)
        assert payload["map"]["lat_approx"] == round(p.lat, 2)
        res = _guess(client, gid, n, 300_000).json()
        assert "listing_url" in res["reveal"]
        payload = res.get("next_round")


def test_full_game_flow_and_scoring(client, seeded):
    g = _new(client)
    gid = g["game_id"]
    total = 0
    for n in range(1, 6):
        p = _prop_for(seeded, gid, n)
        body = _guess(client, gid, n, p.price_usd).json()  # exact USD guess
        rv = body["reveal"]
        assert rv["score"] == 5000 and rv["label"] == "Bullseye!"
        assert rv["price_local"] == p.price_local and rv["currency"] == p.currency
        total += rv["score"]
        if n < 5:
            assert body["next_round"]["round_no"] == n + 1
            assert "summary" not in body
        else:
            assert "next_round" not in body
            s = body["summary"]
            assert s["total_score"] == total == 25_000
            assert s["max_score"] == 25_000
            assert len(s["rounds"]) == 5


def test_hard_mode_payload_has_no_usd(client, seeded):
    g = _new(client, difficulty="hard")
    gid, r = g["game_id"], g["round"]
    p = _prop_for(seeded, gid, 1)
    assert r["difficulty"] == "hard"
    assert r["guess_currency"] == p.currency == r["local_currency"]
    if p.currency != "USD":
        assert r["slider"] != {"min": 5_000, "max": 50_000_000}
        assert "USD" not in json.dumps(r)
    assert not (set(_keys(r)) & PRICE_KEYS)


def test_hard_mode_currency_enforced(client, seeded):
    g = _new(client, difficulty="hard")
    gid = g["game_id"]
    p = _prop_for(seeded, gid, 1)
    wrong = "EUR" if p.currency != "EUR" else "GBP"
    assert _guess(client, gid, 1, 100_000, wrong).status_code == 422
    res = _guess(client, gid, 1, p.price_local, p.currency)
    assert res.status_code == 200
    rv = res.json()["reveal"]
    assert rv["score"] == 5000
    assert rv["guess_local"] == p.price_local


def test_normal_mode_rejects_local_currency(client, seeded):
    g = _new(client)
    p = _prop_for(seeded, g["game_id"], 1)
    if p.currency != "USD":
        assert _guess(client, g["game_id"], 1, 1000, p.currency).status_code == 422


def test_normal_and_hard_equivalent_guess_same_score(client, seeded):
    gn, gh = _new(client), _new(client, difficulty="hard")
    pn = _prop_for(seeded, gn["game_id"], 1)
    ph = _prop_for(seeded, gh["game_id"], 1)
    rn = _guess(client, gn["game_id"], 1, pn.price_usd * 1.3).json()["reveal"]
    rh = _guess(client, gh["game_id"], 1, ph.price_local * 1.3, ph.currency).json()["reveal"]
    assert rn["score"] == rh["score"]


def test_cannot_guess_twice_or_skip(client, seeded):
    gid = _new(client)["game_id"]
    assert _guess(client, gid, 2, 100_000).status_code == 409  # skip ahead
    assert _guess(client, gid, 1, 100_000).status_code == 200
    assert _guess(client, gid, 1, 100_000).status_code == 409  # twice
    assert _guess(client, gid, 6, 100_000).status_code == 404
    assert _guess(client, "nope", 1, 100_000).status_code == 404


@pytest.mark.parametrize("amount", [0, -1, "abc", "100000", None, 1e20])
def test_invalid_guess_amounts(client, seeded, amount):
    gid = _new(client)["game_id"]
    res = client.post(
        f"/api/games/{gid}/rounds/1/guess", json={"amount": amount, "currency": "USD"}
    )
    assert res.status_code == 422


@pytest.mark.parametrize("mode", ["urban", "suburban"])
def test_setting_modes_only_contain_matching_setting(client, seeded, mode):
    for _ in range(5):
        g = _new(client, mode=mode)
        for n in range(1, 6):
            assert _prop_for(seeded, g["game_id"], n).setting == mode


def test_default_games_never_include_rural_or_unknown(client, seeded):
    settings = Counter()
    for _ in range(10):
        g = _new(client)
        for n in range(1, 6):
            settings[_prop_for(seeded, g["game_id"], n).setting] += 1
    assert set(settings) <= {"urban", "suburban"}


def test_country_scope(client, seeded):
    # Seed has only 3-4 per country -> too small for a single-country game.
    res = client.post("/api/games", json={"where_scope": "country", "where_value": "JP"})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "pool_too_small"


def test_region_scope(client, seeded):
    g = _new(client, where_scope="region", where_value="europe")
    for n in range(1, 6):
        assert _prop_for(seeded, g["game_id"], n).country_code in {
            "PT", "ES", "GB", "FR", "IT", "PL", "HR"}  # fmt: skip


@pytest.mark.parametrize(
    "body",
    [
        {"where_scope": "region", "where_value": "atlantis"},
        {"where_scope": "country", "where_value": "DE"},
        {"difficulty": "extreme"},
        {"mode": "daily"},
    ],
)
def test_invalid_create_bodies(client, seeded, body):
    assert client.post("/api/games", json=body).status_code == 422


def test_empty_pool(client):
    assert client.post("/api/games", json={}).status_code == 422


def test_rate_limit(client, seeded, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_games_per_hour", 2)
    security.limiter.reset()
    assert client.post("/api/games", json={}).status_code == 201
    assert client.post("/api/games", json={}).status_code == 201
    assert client.post("/api/games", json={}).status_code == 429


def test_meta(client, seeded):
    m = client.get("/api/meta").json()
    assert len(m["countries"]) == 16
    assert m["world"]["selectable"] is True
    assert m["world"]["eligible"]["total"] == 40
    # 50 required per option -> seed counts are too small for any single option.
    assert not any(c["selectable"] for c in m["countries"])
    jp = next(c for c in m["countries"] if c["code"] == "JP")
    assert jp["eligible"] == {"urban": 2, "suburban": 1, "total": 3}
    assert {r["key"] for r in m["regions"]} == {
        "north_america", "south_america", "europe", "africa", "oceania", "east_asia"}  # fmt: skip
    assert [s["key"] for s in m["sources"]] == ["demo"]
