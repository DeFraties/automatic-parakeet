import json

import httpx
import pytest

from ingest.cache import SqliteCache
from ingest.geocode import Geocoder, precision_from_rank
from ingest.http import SourceBlocked


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def make(tmp_path, handler, url="https://nominatim.openstreetmap.org"):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    ft = FakeTime()
    cache = SqliteCache(tmp_path / "geo.sqlite")
    g = Geocoder(
        user_agent="BallparkBot/test",
        nominatim_url=url,
        postcodes_url="https://api.postcodes.io",
        cache=cache,
        transport=httpx.MockTransport(wrapped),
        sleep=ft.sleep,
        clock=ft.clock,
    )
    return g, calls, ft


def nominatim_then_postcodes(rank):
    def handler(request):
        if request.url.path == "/search":
            data = [{"lat": "53.4", "lon": "-2.2", "place_rank": rank}] if rank else []
            return httpx.Response(200, text=json.dumps(data))
        return httpx.Response(
            200, text=json.dumps({"result": {"latitude": 53.41, "longitude": -2.21}})
        )

    return handler


@pytest.mark.parametrize(
    "rank,precision",
    [
        (30, "exact"),
        (28, "exact"),
        (26, "street"),
        (27, "street"),
        (25, None),
        (16, None),
        (None, None),
    ],
)
def test_precision_from_rank(rank, precision):
    assert precision_from_rank(rank) == precision


def test_building_match_is_exact(tmp_path):
    g, calls, _ = make(tmp_path, nominatim_then_postcodes(30))
    r = g.geocode_address(
        street="12 Example Road", city="Manchester", postcode="ZZ1 1AA", country_code="GB"
    )
    assert (r.lat, r.lng, r.precision) == (53.4, -2.2, "exact")
    q = calls[0].url.params
    assert q["street"] == "12 Example Road" and q["countrycodes"] == "gb"
    assert calls[0].headers["User-Agent"] == "BallparkBot/test"


def test_street_match(tmp_path):
    g, _, _ = make(tmp_path, nominatim_then_postcodes(26))
    assert (
        g.geocode_address(street="x", city="y", postcode="ZZ1 1AA", country_code="GB").precision
        == "street"
    )


def test_falls_back_to_postcode_centroid_as_district(tmp_path):
    g, calls, _ = make(tmp_path, nominatim_then_postcodes(16))
    r = g.geocode_address(street="x", city="y", postcode="ZZ1 1AA", country_code="GB")
    assert r.precision == "district" and r.lat == 53.41
    assert calls[1].url.path == "/postcodes/ZZ11AA"


def test_no_postcode_and_no_match_returns_none(tmp_path):
    g, _, _ = make(tmp_path, nominatim_then_postcodes(None))
    assert g.geocode_address(street="x", city="y", postcode=None, country_code="GB") is None


def test_results_cached_and_addresses_not_stored(tmp_path):
    g, calls, _ = make(tmp_path, nominatim_then_postcodes(30))
    for _ in range(3):
        g.geocode_address(
            street="12 Secret Street", city="Leeds", postcode="ZZ4 4DD", country_code="GB"
        )
    assert len(calls) == 1
    g.cache.close()
    raw = (tmp_path / "geo.sqlite").read_bytes()
    assert b"Secret" not in raw and b"ZZ4" not in raw


def test_public_nominatim_limited_to_one_per_second(tmp_path):
    g, _, ft = make(tmp_path, nominatim_then_postcodes(30))
    for i in range(3):
        g.nominatim(street=f"{i} Road", city="Leeds", postalcode=None, country_code="GB")
    assert len(ft.sleeps) == 2 and all(s >= 1.0 for s in ft.sleeps)


def test_self_hosted_nominatim_not_throttled(tmp_path):
    g, _, ft = make(tmp_path, nominatim_then_postcodes(30), url="http://nominatim.local:8080")
    for i in range(3):
        g.nominatim(street=f"{i} Road", city="Leeds", postalcode=None, country_code="GB")
    assert ft.sleeps == []


def test_geocoder_block_stops(tmp_path):
    g, _, _ = make(tmp_path, lambda r: httpx.Response(429))
    with pytest.raises(SourceBlocked):
        g.nominatim(street="1 Road", city="Leeds", postalcode=None, country_code="GB")


def test_errors_never_include_the_address(tmp_path):
    from ingest.geocode import GeocodeError

    g, _, _ = make(tmp_path, lambda r: httpx.Response(629))
    with pytest.raises(GeocodeError) as e:
        g.nominatim(street="12 Private Lane", city="Leeds", postalcode="ZZ1 1AA", country_code="GB")
    assert "Private" not in str(e.value) and "ZZ1" not in str(e.value)


def test_block_message_names_the_service_not_the_address(tmp_path):
    g, _, _ = make(tmp_path, lambda r: httpx.Response(403))
    with pytest.raises(SourceBlocked) as e:
        g.nominatim(street="12 Private Lane", city="Leeds", postalcode="ZZ1 1AA", country_code="GB")
    msg = str(e.value)
    assert "nominatim.openstreetmap.org" in msg and "SCRAPER_USER_AGENT" in msg
    assert "Private" not in msg and "ZZ1" not in msg
