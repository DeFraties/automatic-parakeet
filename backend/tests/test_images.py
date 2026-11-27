import httpx
import pytest
from sqlalchemy import select

from app.core import images, mapillary, streetview_urls
from app.core.config import get_settings
from app.models import GameRound, Property
from tests.test_api_phase3 import SECRET, H


@pytest.fixture
def keys(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mapillary_token", "MLY|test")
    calls = []

    def mly(request):
        calls.append(request)
        return httpx.Response(
            200, json={"thumb_1024_url": f"https://cdn.mly.test/{request.url.path[1:]}.jpg?exp=1"}
        )

    monkeypatch.setattr(
        mapillary, "resolver", mapillary.ThumbResolver(transport=httpx.MockTransport(mly))
    )
    monkeypatch.setattr(
        streetview_urls,
        "locator",
        streetview_urls.PanoLocator(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"status": "ZERO_RESULTS"})
            )
        ),
    )
    return calls


def prop(db, **kw):
    p = db.execute(select(Property)).scalars().first()
    for k, v in kw.items():
        setattr(p, k, v)
    db.commit()
    return p


def test_listing_photo_wins(seeded, keys):
    p = prop(seeded, image_url="https://photos.example/1.jpg", mly_status="ok", mly_image_id="9")
    img = images.round_image(seeded, p, daily=False)
    assert (img.url, img.source) == ("https://photos.example/1.jpg", "listing")
    assert img.attribution == "Photo: DEMO data (fictional)"


def test_google_before_mapillary_when_key_set(seeded, keys, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_maps_api_key", "K")
    monkeypatch.setattr(s, "google_url_signing_secret", SECRET)
    p = prop(seeded, pano_id="PANO", sv_status="ok", mly_status="ok", mly_image_id="9")
    assert images.round_image(seeded, p, daily=False).source == "google"


def test_mapillary_used_without_google(seeded, keys):
    p = prop(seeded, pano_id="PANO", sv_status="ok", mly_status="ok", mly_image_id="12345")
    img = images.round_image(seeded, p, daily=False)
    assert img.source == "mapillary" and img.url == "https://cdn.mly.test/12345.jpg?exp=1"
    assert "CC BY-SA" in img.attribution
    assert keys[0].headers["Authorization"] == "OAuth MLY|test"
    images.round_image(seeded, p, daily=False)
    assert len(keys) == 1  # thumbnail URL cached in memory


def test_no_image_sources(seeded, keys, monkeypatch):
    monkeypatch.setattr(get_settings(), "mapillary_token", "")
    p = prop(seeded, mly_status="ok", mly_image_id="1")
    assert images.round_image(seeded, p, daily=False) == images.NO_IMAGE


def test_mapillary_failure_falls_through(seeded, monkeypatch):
    monkeypatch.setattr(get_settings(), "mapillary_token", "T")
    monkeypatch.setattr(
        mapillary,
        "resolver",
        mapillary.ThumbResolver(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    p = prop(seeded, mly_status="ok", mly_image_id="1")
    assert images.round_image(seeded, p, daily=False) == images.NO_IMAGE


@pytest.mark.parametrize(
    "source,before,after",
    [
        ("listing", {"image_url": "https://x/1.jpg"}, {"image_url": None}),
        ("mapillary", {"mly_status": "ok", "mly_image_id": "1"}, {"mly_status": "unchecked"}),
        ("google", {"sv_status": "ok", "pano_id": "P"}, {"sv_status": "unchecked"}),
    ],
)
def test_image_error_forgets_only_that_link(client, seeded, source, before, after):
    g = client.post("/api/games", json={}, headers=H()).json()
    pid = seeded.get(GameRound, (g["game_id"], 1)).property_id
    p = seeded.get(Property, pid)
    for k, v in before.items():
        setattr(p, k, v)
    seeded.commit()
    r = client.post(
        "/api/telemetry/image-error",
        json={"game_id": g["game_id"], "round_no": 1, "source": source},
        headers=H(),
    )
    assert r.status_code == 204
    seeded.expire_all()
    p = seeded.get(Property, pid)
    for k, v in after.items():
        assert getattr(p, k) == v
    assert p.is_active  # the home itself is never removed by a report


def test_round_payload_reports_listing_photo(client, seeded):
    for p in seeded.execute(select(Property)).scalars():
        p.image_url = f"https://photos.example/{p.source_ref}.jpg"
    seeded.commit()
    r = client.post("/api/games", json={}, headers=H()).json()["round"]
    assert r["image_source"] == "listing" and r["image_url"].startswith("https://photos.example/")


def _graph(images_response):
    """Mock Graph API: /images returns `images_response`; /{id} returns a thumbnail."""
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/images":
            return images_response(request)
        return httpx.Response(
            200, json={"thumb_1024_url": f"https://cdn.mly.test{request.url.path}.jpg"}
        )

    return mapillary.ThumbResolver(transport=httpx.MockTransport(handler)), calls


def _facing_image(p):
    # 20 m south of the house, camera pointing north (at it)
    return {
        "id": "777",
        "is_pano": False,
        "computed_compass_angle": 0,
        "computed_geometry": {"type": "Point", "coordinates": [p.lng, p.lat - 20 / 111_320]},
    }


def test_unchecked_home_is_checked_on_the_fly(seeded, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "mapillary_token", "MLY|t")
    p = prop(seeded, mly_status="unchecked", mly_image_id=None, location_precision="exact")
    resolver, calls = _graph(lambda r: httpx.Response(200, json={"data": [_facing_image(p)]}))
    monkeypatch.setattr(mapillary, "resolver", resolver)
    img = images.round_image(seeded, p, daily=False)
    assert img.source == "mapillary" and img.url == "https://cdn.mly.test/777.jpg"
    seeded.expire_all()
    p = seeded.get(Property, p.id)
    assert (p.mly_status, p.mly_image_id) == ("ok", "777")  # saved for next time
    images.round_image(seeded, p, daily=False)
    assert sum(c.url.path == "/images" for c in calls) == 1  # no second search


def test_on_the_fly_no_photo_nearby_is_remembered(seeded, monkeypatch):
    monkeypatch.setattr(get_settings(), "mapillary_token", "MLY|t")
    p = prop(seeded, mly_status="unchecked", location_precision="street")
    resolver, _ = _graph(lambda r: httpx.Response(200, json={"data": []}))
    monkeypatch.setattr(mapillary, "resolver", resolver)
    assert images.round_image(seeded, p, daily=False) == images.NO_IMAGE
    seeded.expire_all()
    assert seeded.get(Property, p.id).mly_status == "none"


def test_on_the_fly_api_error_leaves_unchecked_and_logs(seeded, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "mapillary_token", "MLY|bad")
    p = prop(seeded, mly_status="unchecked", location_precision="exact")
    resolver, _ = _graph(lambda r: httpx.Response(401, json={"error": "invalid token"}))
    monkeypatch.setattr(mapillary, "resolver", resolver)
    assert images.round_image(seeded, p, daily=False) == images.NO_IMAGE
    seeded.expire_all()
    assert seeded.get(Property, p.id).mly_status == "unchecked"
    assert "HTTP 401" in caplog.text and "MLY|bad" not in caplog.text


def test_district_homes_not_looked_up(seeded, monkeypatch):
    monkeypatch.setattr(get_settings(), "mapillary_token", "MLY|t")
    p = prop(seeded, mly_status="unchecked", location_precision="district")
    resolver, calls = _graph(lambda r: httpx.Response(200, json={"data": []}))
    monkeypatch.setattr(mapillary, "resolver", resolver)
    images.round_image(seeded, p, daily=False)
    assert calls == []


def test_game_rounds_get_mapillary_photos_without_running_the_check(client, seeded, monkeypatch):
    # With illustrations allowed, unchecked homes can be dealt and get checked on the fly.
    monkeypatch.setattr(get_settings(), "mapillary_token", "MLY|t")
    monkeypatch.setattr(get_settings(), "allow_imageless_rounds", True)

    def images_near(request):
        w, s, e, n = map(float, request.url.params["bbox"].split(","))
        lat, lng = (s + n) / 2, (w + e) / 2
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "42",
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

    resolver, _ = _graph(images_near)
    monkeypatch.setattr(mapillary, "resolver", resolver)
    g = client.post("/api/games", json={}, headers=H()).json()
    assert g["round"]["image_source"] == "mapillary"
    assert g["round"]["attribution"].startswith("© Mapillary")
