import httpx
import pytest
from sqlalchemy import select

from app.core import mapillary, photo_checker
from app.core.config import get_settings
from app.core.images import imageless_allowed
from app.models import GameRound, Property
from tests.test_api_phase3 import H


def resolver_with(images_near):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/images":
            return images_near(request)
        return httpx.Response(
            200, json={"thumb_1024_url": f"https://cdn.mly.test{request.url.path}.jpg"}
        )

    return mapillary.ThumbResolver(transport=httpx.MockTransport(handler)), calls


def photo_for_every_other_home(request):
    """A facing photo 20 m south of the bbox centre, for about half the homes."""
    w, s, e, n = map(float, request.url.params["bbox"].split(","))
    lat, lng = (s + n) / 2, (w + e) / 2
    if int(abs(lat) * 1000) % 2:
        return httpx.Response(200, json={"data": []})
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": f"m{abs(lat):.4f}",
                    "is_pano": False,
                    "computed_compass_angle": 0,
                    "computed_geometry": {
                        "type": "Point",
                        "coordinates": [lng, lat - 20 / 111_320],
                    },
                }
            ]
        },
    )


@pytest.fixture
def mly(monkeypatch):
    monkeypatch.setattr(get_settings(), "mapillary_token", "MLY|t")
    resolver, calls = resolver_with(photo_for_every_other_home)
    monkeypatch.setattr(mapillary, "resolver", resolver)
    return calls


def test_imageless_rule():
    s = get_settings()
    assert s.allow_imageless_rounds is False  # owner decision: photos required
    assert imageless_allowed() is True  # ...but no photo source configured -> still playable


def test_imageless_not_allowed_once_a_source_exists(mly):
    assert imageless_allowed() is False


def test_check_batch_and_pending(seeded, mly):
    assert photo_checker.pending_count(seeded) == 51
    assert photo_checker.check_batch(seeded, "MLY|t", limit=20) == 20
    assert photo_checker.pending_count(seeded) == 31
    while photo_checker.check_batch(seeded, "MLY|t"):
        pass
    statuses = {p.mly_status for p in seeded.execute(select(Property)).scalars()}
    assert statuses == {"ok", "none"}


def test_check_batch_stops_on_api_error(seeded, monkeypatch):
    resolver, _ = resolver_with(lambda r: httpx.Response(401))
    monkeypatch.setattr(mapillary, "resolver", resolver)
    with pytest.raises(mapillary.MapillaryError):
        photo_checker.check_batch(seeded, "MLY|bad")
    assert photo_checker.pending_count(seeded) == 51


def test_only_homes_with_photos_are_played(client, seeded, mly):
    # Before any check: nothing has a photo, so nothing is playable.
    r = client.post("/api/games", json={"settings": ["urban", "suburban", "rural"]}, headers=H())
    assert r.status_code == 422
    meta = client.get("/api/meta").json()
    assert meta["photos_required"] is True and meta["photo_check_pending"] == 51
    while photo_checker.check_batch(seeded, "MLY|t"):
        pass
    with_photo = {p.id for p in seeded.execute(select(Property)).scalars() if p.mly_status == "ok"}
    assert len(with_photo) >= 5
    for _ in range(5):
        g = client.post(
            "/api/games", json={"settings": ["urban", "suburban", "rural"]}, headers=H()
        ).json()
        assert g["round"]["image_source"] == "mapillary"
        ids = {
            r.property_id
            for r in seeded.execute(
                select(GameRound).where(GameRound.game_id == g["game_id"])
            ).scalars()
        }
        assert ids <= with_photo
    assert client.get("/api/meta").json()["photo_check_pending"] == 0


def test_background_checker_needs_token_and_flag(monkeypatch):
    monkeypatch.setattr(get_settings(), "background_photo_check", True)
    assert photo_checker.start_background_checker() is None  # no token


def test_background_checker_single_instance(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "background_photo_check", True)
    monkeypatch.setattr(s, "mapillary_token", "MLY|t")
    monkeypatch.setattr(s, "ingest_cache_dir", str(tmp_path))
    monkeypatch.setattr(photo_checker.BackgroundPhotoChecker, "run", lambda self: None)
    monkeypatch.setattr(photo_checker, "_lock_handle", None)
    first = photo_checker.start_background_checker()
    assert first is not None
    import fcntl

    other = open(tmp_path / "photo_checker.lock", "w")  # noqa: SIM115
    with pytest.raises(OSError):
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # held by the first checker
    other.close()
    photo_checker._lock_handle.close()
