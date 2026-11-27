"""Open geocoding for sources without coordinates (Section 8.4 / Compliance rule 3).

Never uses Google. Nominatim first (max 1 request/second on the public server, honest
User-Agent, cached), then a postcode centroid from postcodes.io as a district-level fallback.
Cache keys are SHA-256 hashes so addresses are never written to disk; results only hold
coordinates and a precision.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ingest.cache import SqliteCache, hash_key
from ingest.http import SourceBlocked

log = logging.getLogger(__name__)

PUBLIC_NOMINATIM_HOST = "nominatim.openstreetmap.org"


class GeocodeError(Exception):
    pass


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lng: float
    precision: str  # exact | street | district


def precision_from_rank(place_rank: int | None, osm_type: str | None = None) -> str | None:
    """Nominatim place_rank: 30 = building/house, 28 = house-number interpolation, 26-27 = street.
    Anything coarser isn't good enough to point Street View at."""
    if place_rank is None:
        return None
    if place_rank >= 28:
        return "exact"
    if place_rank >= 26:
        return "street"
    return None


class Geocoder:
    def __init__(
        self,
        *,
        user_agent: str,
        nominatim_url: str,
        postcodes_url: str,
        cache: SqliteCache,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.nominatim_url = nominatim_url.rstrip("/")
        self.postcodes_url = postcodes_url.rstrip("/")
        public = urlsplit(self.nominatim_url).netloc == PUBLIC_NOMINATIM_HOST
        self.min_interval = 1.05 if public else 0.0  # public usage policy: max 1 req/s
        self.cache = cache
        self._sleep = sleep or time.sleep
        self._clock = clock
        self._last: float | None = None
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=30,
            transport=transport,
            follow_redirects=True,
        )
        self.requests_made = 0

    def close(self) -> None:
        self._http.close()

    def _throttle(self) -> None:
        if self._last is not None and self.min_interval:
            remaining = self.min_interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

    def _get_json(self, url: str, params: dict | None = None):
        self.requests_made += 1
        resp = self._http.get(url, params=params)
        if resp.status_code in (403, 429):
            host = urlsplit(url).netloc  # host only: the full URL contains the address
            hint = (
                " Set SCRAPER_USER_AGENT in .env to identify you (with a real contact email)."
                if resp.status_code == 403
                else ""
            )
            raise SourceBlocked(f"{host} refused the request (HTTP {resp.status_code}).{hint}")
        if resp.status_code == 404:
            return None
        if not 200 <= resp.status_code < 300:
            # Deliberately no URL in the message: geocoder URLs contain street addresses.
            raise GeocodeError(f"geocoder returned HTTP {resp.status_code}")
        return resp.json()

    def nominatim(
        self, *, street: str, city: str, postalcode: str | None, country_code: str
    ) -> GeoResult | None:
        params = {
            "street": street,
            "city": city,
            "countrycodes": country_code.lower(),
            "format": "jsonv2",
            "limit": 1,
        }
        if postalcode:
            params["postalcode"] = postalcode
        key = hash_key("nominatim", *(f"{k}={v}" for k, v in sorted(params.items())))
        hit = self.cache.get("geocode", key)
        if hit is not None:
            return GeoResult(**hit) if hit else None
        self._throttle()
        data = self._get_json(f"{self.nominatim_url}/search", params)
        result = None
        if isinstance(data, list) and data:
            top = data[0]
            precision = precision_from_rank(top.get("place_rank"))
            if precision:
                result = GeoResult(float(top["lat"]), float(top["lon"]), precision)
        self.cache.set("geocode", key, result.__dict__ if result else {})
        return result

    def postcode_centroid(self, postcode: str) -> GeoResult | None:
        pc = postcode.replace(" ", "").upper()
        key = hash_key("postcodes.io", pc)
        hit = self.cache.get("geocode", key)
        if hit is not None:
            return GeoResult(**hit) if hit else None
        data = self._get_json(f"{self.postcodes_url}/postcodes/{pc}")
        result = None
        if data and data.get("result") and data["result"].get("latitude") is not None:
            r = data["result"]
            result = GeoResult(float(r["latitude"]), float(r["longitude"]), "district")
        self.cache.set("geocode", key, result.__dict__ if result else {})
        return result

    def geocode_address(
        self, *, street: str, city: str, postcode: str | None, country_code: str
    ) -> GeoResult | None:
        """Full-address lookup, falling back to the postcode centroid (district precision)."""
        result = None
        if street and city:
            result = self.nominatim(
                street=street, city=city, postalcode=postcode, country_code=country_code
            )
        if result is None and postcode:
            result = self.postcode_centroid(postcode)
        return result
