"""Street View Static API URL building (Section 7.3).

At round time: look up the panorama's location with the (free) metadata endpoint, cached in
memory for 10 minutes and never persisted; point the camera at the property; sign the URL. The
browser loads the image straight from Google. The server never downloads image bytes.
"""

import base64
import hashlib
import hmac
import math
import threading
import time
from urllib.parse import urlencode, urlparse

import httpx

STREETVIEW_BASE = "https://maps.googleapis.com/maps/api/streetview"
METADATA_URL = f"{STREETVIEW_BASE}/metadata"
PANO_CACHE_TTL_S = 600
ATTRIBUTION = "© Google"


def initial_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees in [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def sign_url(url: str, secret_b64: str) -> str:
    """Sign a Google Maps Platform URL with a URL-safe base64 signing secret."""
    parsed = urlparse(url)
    to_sign = parsed.path + ("?" + parsed.query if parsed.query else "")
    key = base64.urlsafe_b64decode(secret_b64)
    sig = hmac.new(key, to_sign.encode(), hashlib.sha1).digest()
    return f"{url}&signature={base64.urlsafe_b64encode(sig).decode()}"


def build_streetview_url(pano_id: str, heading: float | None, api_key: str, secret_b64: str) -> str:
    params: dict = {"size": "640x640", "pano": pano_id}
    if heading is not None:
        params["heading"] = f"{round(heading, 1) % 360:.1f}"  # 359.97 -> 0.0, not 360.0
    params.update({"pitch": 5, "fov": 80, "key": api_key})
    return sign_url(f"{STREETVIEW_BASE}?{urlencode(params)}", secret_b64)


class PanoLocator:
    """Panorama location lookups via the metadata endpoint, cached in memory for 10 minutes."""

    def __init__(
        self, transport: httpx.BaseTransport | None = None, ttl_s: float = PANO_CACHE_TTL_S
    ):
        self._http = httpx.Client(timeout=5, transport=transport)
        self._cache: dict[str, tuple[float, tuple[float, float] | None]] = {}
        self._lock = threading.Lock()
        self.ttl_s = ttl_s

    def locate(self, pano_id: str, api_key: str) -> tuple[float, float] | None:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(pano_id)
            if hit and now - hit[0] < self.ttl_s:
                return hit[1]
        loc = None
        try:
            resp = self._http.get(METADATA_URL, params={"pano": pano_id, "key": api_key})
            data = resp.json() if resp.status_code == 200 else {}
            if data.get("status") == "OK" and data.get("location"):
                loc = (float(data["location"]["lat"]), float(data["location"]["lng"]))
        except (httpx.HTTPError, ValueError):
            loc = None
        with self._lock:
            self._cache[pano_id] = (now, loc)
            if len(self._cache) > 5000:  # keep memory bounded
                for k in sorted(self._cache, key=lambda k: self._cache[k][0])[:1000]:
                    self._cache.pop(k, None)
        return loc

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


locator = PanoLocator()


def image_for(
    pano_id: str | None, lat: float, lng: float, *, api_key: str, secret: str, loc=None
) -> str | None:
    """Signed Street View URL facing the property, or None without a key or panorama."""
    if not (pano_id and api_key and secret):
        return None
    pano_loc = loc if loc is not None else locator.locate(pano_id, api_key)
    heading = initial_bearing(*pano_loc, lat, lng) if pano_loc else None
    return build_streetview_url(pano_id, heading, api_key, secret)
