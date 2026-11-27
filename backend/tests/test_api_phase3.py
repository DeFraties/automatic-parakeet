import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import daily as daily_core
from app.core.profanity import nickname_problem
from app.models import (
    DailyChallenge,
    GameRound,
    LeaderboardEntry,
    PhotoReport,
    Property,
    RemovalRequest,
)


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

    d = daily_core.utc_today()
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
    for ok in ("Alice", "Bob_99", "Zoë", "J. Smith", "Sam"):
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
    assert today["entries"][0]["date"] == daily_core.utc_today().isoformat()
    yesterday = (daily_core.utc_today() - timedelta(days=1)).isoformat()
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


# -------------------------------------------------------------------- Telemetry/removals ----
def _round_prop(db, gid, n=1):
    pid = db.get(GameRound, (gid, n)).property_id
    db.expire_all()
    return db.get(Property, pid)


def test_image_error_marks_photos_broken_and_drops_home_below_two(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    gid = g["game_id"]
    p = _round_prop(seeded, gid)
    positions = [ph["position"] for ph in g["round"]["photos"]]
    assert len(positions) >= 3
    r = client.post(
        "/api/telemetry/image-error",
        json={"game_id": gid, "round_no": 1, "positions": positions[:1]},
        headers=H(),
    )
    assert r.status_code == 204
    p = _round_prop(seeded, gid)
    assert p.images_status == "ok"  # still >= 2 working
    statuses = {i.position: i.status for i in p.images}
    assert statuses[positions[0]] == "broken"
    client.post(
        "/api/telemetry/image-error",
        json={"game_id": gid, "round_no": 1, "positions": positions},
        headers=H(),
    )
    assert _round_prop(seeded, gid).images_status == "broken"  # out of the pool


def test_image_error_only_for_rounds_shown(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    r = client.post(
        "/api/telemetry/image-error",
        json={"game_id": g["game_id"], "round_no": 4, "positions": [0]},
        headers=H(),
    )
    assert r.status_code == 404
    r = client.post(
        "/api/telemetry/image-error",
        json={"game_id": g["game_id"], "round_no": 1, "positions": [0]},
        headers=H("other-device"),
    )
    assert r.status_code == 404


def test_price_visible_report_removes_home_from_play(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    p = _round_prop(seeded, g["game_id"])
    r = client.post(
        "/api/reports",
        json={"game_id": g["game_id"], "round_no": 1, "position": 0, "reason": "price_visible"},
        headers=H(),
    )
    assert r.status_code == 201
    rep = seeded.execute(select(PhotoReport)).scalar_one()
    assert (rep.reason, rep.status, rep.property_id) == ("price_visible", "open", p.id)
    for _ in range(15):
        g2 = client.post("/api/games", json={}, headers=H()).json()
        ids = {
            x.property_id
            for x in seeded.execute(
                select(GameRound).where(GameRound.game_id == g2["game_id"])
            ).scalars()
        }
        assert p.id not in ids
    rep.status = "dismissed"
    seeded.commit()
    from app.core.selection import load_candidates

    assert p.id in {
        c.id
        for c in load_candidates(
            seeded, today=daily_core.utc_today(), max_age_years=2, setting_filter="rural,urban"
        )
    }


def test_other_reports_dont_remove_home(client, seeded):
    g = client.post("/api/games", json={}, headers=H()).json()
    for reason in ("broken", "person", "other"):
        assert (
            client.post(
                "/api/reports",
                json={"game_id": g["game_id"], "round_no": 1, "reason": reason},
                headers=H(),
            ).status_code
            == 201
        )
    assert (
        client.post(
            "/api/reports",
            json={"game_id": g["game_id"], "round_no": 1, "reason": "spam"},
            headers=H(),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/reports",
            json={"game_id": g["game_id"], "round_no": 3, "reason": "other"},
            headers=H(),
        ).status_code
        == 404
    )


def test_no_route_serves_or_proxies_image_bytes():
    """Section 13.2: photos are hotlinked; the API never serves, proxies or redirects to images."""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        assert not any(w in path.lower() for w in ("image/", "proxy", "photo/", "thumb")), path
        if path:
            assert path.startswith(("/api", "/docs", "/redoc")) or "openapi" in path, path


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
