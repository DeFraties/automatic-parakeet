import pytest

from app.core.streetview_urls import build_streetview_url, initial_bearing, sign_url


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ((0, 0), (1, 0), 0),  # due north
        ((0, 0), (0, 1), 90),  # due east
        ((1, 0), (0, 0), 180),  # due south
        ((0, 1), (0, 0), 270),  # due west
        # Known pair: Baghdad (35N, 45E) -> Osaka (35N, 135E): ~60.16 deg
        ((35, 45), (35, 135), 60.16),
    ],
)
def test_initial_bearing(a, b, expected):
    assert initial_bearing(*a, *b) == pytest.approx(expected, abs=0.01)


def test_url_signing_matches_google_documented_example():
    # Example from Google Maps Platform "Digital signatures" documentation.
    url = "https://maps.googleapis.com/maps/api/geocode/json?address=New+York&client=clientID"
    signed = sign_url(url, "vNIXE0xscrmjlyV-12Nj_BvUPaw=")
    assert signed == url + "&signature=chaRF2hTJKOScPr-RQCEhZbSzIE="


def test_build_streetview_url():
    url = build_streetview_url("PANO123", 123.456, "KEY", "vNIXE0xscrmjlyV-12Nj_BvUPaw=")
    assert url.startswith(
        "https://maps.googleapis.com/maps/api/streetview?size=640x640&pano=PANO123"
    )
    assert "heading=123.5" in url and "pitch=5" in url and "fov=80" in url
    assert "&signature=" in url
