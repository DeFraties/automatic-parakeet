import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.core import quota, streetview_urls
from app.core.config import get_settings
from app.core.profanity import nickname_problem
from app.models import (
    DailyChallenge,
    GameRound,
    LeaderboardEntry,
    Property,
    RemovalRequest,
    SvUsage,
)

SECRET = base64.urlsafe_b64encode(b"test-signing-secret").decode()


def H(device="dev-1"):  # noqa: N802
    return {"X-Device-Id": device}


def play_through(client, start, device="dev-1", amount=300_000):
    gid = start["game_id"]
    body = None
    for n in range(1, 6):
        cur = (start["round"] if n == 1 else body["next_round"])["guess_currency"]
        body = client.post(
            f"/api/games/{gid}/rounds/{n}/guess",
            json={"amount": amount, "currency": cur},
            headers=H(device),
        ).json()
    return body["summary"]


# ---------------------------------------------------------------------------------- Daily ----
def test_daily_same_properties_for_everyone_and_both_difficulties(client, seeded):
    a = client.post("/api/daily/start", json={}, headers=H("a")).json()
    b = client.post("/api/daily/start", json={"difficulty": "hard"}, headers=H("b")).json()
    assert a["mode"] == "daily" and b["difficulty"] == "hard"
    assert a["where_scope"] == "world" and sorted(a["settings"]) == ["rural", "urban"]

    def ids(g):
        return [
            r.property_id
            for r in seeded.execute(
                select(GameRound)
                .where(GameRound.game_id == g["game_id"])
                .order_by(GameRound.round_no)
            ).scalars()
        ]

    assert ids(a) == ids(b)
    row = seeded.execute(select(DailyChallenge)).scalar_one()
    assert row.property_ids == ids(a)


def test_daily_second_attempt_is_409(client, seeded):
    assert client.post("/api/daily/start", json={}, headers=H()).status_code == 201
    r = client.post("/api/daily/start", json={"difficulty": "hard"}, headers=H())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_played"


def test_daily_requires_device(client, seeded):
    assert client.post("/api/daily/start", json={}).status_code == 400


def test_daily_status_and_resume(client, seeded):
    st = client.get("/api/daily", headers=H()).json()
    assert st["played"] is False and st["number"] >= 1
    g = client.post("/api/daily/start", json={}, headers=H()).json()
    st = client.get("/api/daily", headers=H()).json()
    assert st["played"] and not st["completed"] and st["game_id"] == g["game_id"]
    # resume mid-game
    client.post(
        f"/api/games/{g['game_id']}/rounds/1/guess",
        json={"amount": 300000, "currency": "USD"},
        headers=H(),
    )
    resumed = client.get(f"/api/games/{g['game_id']}", headers=H()).json()
    assert resumed["round"]["round_no"] == 2 and resumed["score"] >= 0
    assert "price_local" not in json.dumps(resumed["round"])
    assert client.get(f"/api/games/{g['game_id']}", headers=H("other")).status_code == 404
    summary = play_through_rest(client, g["game_id"], start_round=2)
    st = client.get("/api/daily", headers=H()).json()
    assert st["completed"] and st["score"] == summary["total_score"]
    done = client.get(f"/api/games/{g['game_id']}", headers=H()).json()
    assert done["summary"]["total_score"] == summary["total_score"]


def play_through_rest(client, gid, start_round):
    for n in range(start_round, 6):
        body = client.post(
            f"/api/games/{gid}/rounds/{n}/guess",
            json={"amount": 300000, "currency": "USD"},
            headers=H(),
        ).json()
    return body["summary"]


def test_daily_is_deterministic_for_a_date(seeded):
    from app.core import daily

    d = quota.utc_today()
    assert daily.generate_ids(seeded, d) == daily.generate_ids(seeded, d)
    assert daily.generate_ids(seeded, d) != daily.generate_ids(seeded, d + timedelta(days=1))


def test_daily_number():
    from datetime import date

    from app.core.daily import daily_number

    assert daily_number(date(2027, 1, 1), date(2027, 1, 1)) == 1
    assert daily_number(date(2027, 5, 22), date(2027, 1, 1)) == 142
    assert daily_number(date(2026, 1, 1), date(2027, 1, 1)) == 1  # before launch


# --------------------------------------------------------------------------- Leaderboards ----
def test_leaderboard_rejects_incomplete_and_uses_server_score(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    r = client.post(
        "/api/leaderboards", json={"game_id": g["game_id"], "nickname": "Alice"}, headers=H()
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_completed"
    summary = play_through(client, g)
    r = client.post(
        "/api/leaderboards",
        json={"game_id": g["game_id"], "nickname": "Alice", "score": 25000},
        headers=H(),
    )
    assert r.status_code == 201 and r.json()["score"] == summary["total_score"]
    assert seeded.execute(select(LeaderboardEntry.score)).scalar_one() == summary["total_score"]
    dup = client.post(
        "/api/leaderboards", json={"game_id": g["game_id"], "nickname": "Alice"}, headers=H()
    )
    assert dup.status_code == 409


def test_leaderboard_other_device_cannot_submit(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    play_through(client, g)
    r = client.post(
        "/api/leaderboards",
        json={"game_id": g["game_id"], "nickname": "Mallory"},
        headers=H("someone-else"),
    )
    assert r.status_code == 404


@pytest.mark.parametrize("nick", ["ab", "x" * 17, "f*ck", "Sh1thead", "kurwa123", "<script>"])
def test_bad_nicknames_rejected(client, seeded, nick):
    g = client.post("/api/games", json={}, headers=H()).json()
    play_through(client, g)
    r = client.post(
        "/api/leaderboards", json={"game_id": g["game_id"], "nickname": nick}, headers=H()
    )
    assert r.status_code == 422


def test_nickname_filter_allows_normal_names():
    for ok in ("Alice", "Bob_99", "Zoë", "J. Smith", "Scunthorpe-x"[:3]):
        assert nickname_problem(ok) is None, ok


def _submit(client, device, nickname, **game):
    g = client.post("/api/games", json=game, headers=H(device)).json()
    play_through(client, g, device=device)
    r = client.post(
        "/api/leaderboards", json={"game_id": g["game_id"], "nickname": nickname}, headers=H(device)
    )
    assert r.status_code == 201, r.text


def test_boards_never_mix_difficulty_where_or_settings(client, seeded):
    _submit(client, "d1", "NormalWorld")
    _submit(client, "d2", "HardWorld", difficulty="hard")
    _submit(client, "d3", "Europe", where_scope="region", where_value="europe")
    _submit(client, "d4", "UrbanOnly", settings=["urban"])

    def names(**params):
        r = client.get("/api/leaderboards/classic", params=params).json()
        return [e["nickname"] for e in r["entries"]]

    assert names() == ["NormalWorld"]
    assert names(difficulty="hard") == ["HardWorld"]
    assert names(where_scope="region", where_value="europe") == ["Europe"]
    assert names(settings="urban") == ["UrbanOnly"]
    assert names(settings="rural,urban", period="day") == ["NormalWorld"]
    e = client.get(
        "/api/leaderboards/classic", params={"where_scope": "region", "where_value": "europe"}
    ).json()["entries"][0]
    assert e["flag"] == "🌍" and e["rank"] == 1


def test_daily_board_by_date(client, seeded):
    g = client.post("/api/daily/start", json={}, headers=H("p1")).json()
    play_through(client, g, device="p1")
    client.post(
        "/api/leaderboards", json={"game_id": g["game_id"], "nickname": "DailyDan"}, headers=H("p1")
    )
    today = client.get("/api/leaderboards/daily").json()
    assert [e["nickname"] for e in today["entries"]] == ["DailyDan"]
    assert today["entries"][0]["date"] == quota.utc_today().isoformat()
    yesterday = (quota.utc_today() - timedelta(days=1)).isoformat()
    assert client.get("/api/leaderboards/daily", params={"date": yesterday}).json()["entries"] == []
    assert (
        client.get("/api/leaderboards/daily", params={"difficulty": "hard"}).json()["entries"] == []
    )


def test_ranking_order(client, seeded):
    for i, amount in enumerate((300_000, 10_000_000)):
        g = client.post("/api/games", json={}, headers=H(f"r{i}")).json()
        play_through(client, g, device=f"r{i}", amount=amount)
        client.post(
            "/api/leaderboards",
            json={"game_id": g["game_id"], "nickname": f"Player{i}"},
            headers=H(f"r{i}"),
        )
    scores = [e["score"] for e in client.get("/api/leaderboards/classic").json()["entries"]]
    assert scores == sorted(scores, reverse=True)


# ------------------------------------------------------------------ Street View + quota ----
@pytest.fixture
def google(monkeypatch, seeded):
    s = get_settings()
    monkeypatch.setattr(s, "google_maps_api_key", "TESTKEY")
    monkeypatch.setattr(s, "google_url_signing_secret", SECRET)
    monkeypatch.setattr(s, "google_daily_quota", 25)
    monkeypatch.setattr(s, "daily_reserved", 10)
    for p in seeded.execute(select(Property)).scalars():
        p.pano_id = f"PANO-{p.source_ref}"
    seeded.commit()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "OK", "location": {"lat": 0.0, "lng": 0.0}})

    loc = streetview_urls.PanoLocator(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(streetview_urls, "locator", loc)
    return calls


def test_round_has_signed_streetview_url_facing_house(client, google, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    r = g["round"]
    assert r["image_source"] == "google"
    url = urlparse(r["image_url"])
    q = parse_qs(url.query)
    assert url.netloc == "maps.googleapis.com" and url.path == "/maps/api/streetview"
    assert q["pano"][0].startswith("PANO-") and q["key"] == ["TESTKEY"] and "signature" in q
    assert q["size"] == ["640x640"] and q["pitch"] == ["5"] and q["fov"] == ["80"]
    assert 0 <= float(q["heading"][0]) < 360
    assert r["attribution"] == "© Google"
    assert google[0].url.params["pano"].startswith("PANO-")  # metadata looked up live


def test_pano_location_cached_in_memory(client, google):
    loc = streetview_urls.locator
    loc.locate("PANO-X", "TESTKEY")
    loc.locate("PANO-X", "TESTKEY")
    assert sum(c.url.params["pano"] == "PANO-X" for c in google) == 1


def test_quota_blocks_new_games_but_daily_uses_reserve(client, google, seeded):
    # budget for non-daily = 25 - 10 = 15 URLs = 3 full games
    for i in range(3):
        g = client.post("/api/games", json={}, headers=H(f"q{i}")).json()
        play_through(client, g, device=f"q{i}")
    r = client.post("/api/games", json={}, headers=H())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "quota_exceeded"
    assert "come back tomorrow" in r.json()["detail"]["message"]
    usage = seeded.get(SvUsage, quota.utc_today())
    seeded.refresh(usage)
    assert usage.urls_issued == 15
    assert client.get("/api/meta").json()["quota"] == {
        "games_available": False,
        "daily_available": True,
    }
    d = client.post("/api/daily/start", json={}, headers=H("daily-1"))
    assert d.status_code == 201
    play_through(client, d.json(), device="daily-1")
    seeded.refresh(usage)
    assert (usage.urls_issued, usage.daily_reserved_used) == (20, 5)
    # 25 - 20 = 5 left: one more Daily fits, then nothing
    d2 = client.post("/api/daily/start", json={}, headers=H("daily-2"))
    assert d2.status_code == 201
    play_through(client, d2.json(), device="daily-2")
    assert client.post("/api/daily/start", json={}, headers=H("daily-3")).status_code == 503


def test_no_key_means_placeholder_and_no_quota(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    assert g["round"]["image_url"] is None and g["round"]["attribution"] is None
    assert g["round"]["image_source"] is None
    assert seeded.get(SvUsage, quota.utc_today()) is None


# -------------------------------------------------------------------- Telemetry/removals ----
def test_image_error_sends_property_back_for_recheck(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    r = client.post(
        "/api/telemetry/image-error", json={"game_id": g["game_id"], "round_no": 1}, headers=H()
    )
    assert r.status_code == 204
    pid = seeded.get(GameRound, (g["game_id"], 1)).property_id
    seeded.expire_all()
    assert seeded.get(Property, pid).sv_status == "unchecked"


def test_image_error_only_for_rounds_shown(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    r = client.post(
        "/api/telemetry/image-error", json={"game_id": g["game_id"], "round_no": 4}, headers=H()
    )
    assert r.status_code == 404
    r = client.post(
        "/api/telemetry/image-error",
        json={"game_id": g["game_id"], "round_no": 1},
        headers=H("other-device"),
    )
    assert r.status_code == 404


def test_removal_request_stored(client, seeded):
    r = client.post(
        "/api/removals",
        json={
            "email": "owner@example.com",
            "reference": "https://example.com/demo/demo-001",
            "message": "This is my house",
        },
    )
    assert r.status_code == 201
    row = seeded.execute(select(RemovalRequest)).scalar_one()
    assert (row.email, row.status) == ("owner@example.com", "pending")


@pytest.mark.parametrize(
    "body",
    [
        {"email": "nope", "reference": "abc"},
        {"email": "a@b.co", "reference": ""},
        {"email": "a@b.co", "reference": "x" * 1001},
    ],
)
def test_removal_validation(client, seeded, body):
    assert client.post("/api/removals", json=body).status_code == 422
