"""Mapillary street-level imagery (GDD Section 7.5, owner change 2026-11-27).

Only the Mapillary image ID is stored. At round time the server asks Mapillary's Graph API for
the image's current thumbnail URL (these CDN URLs expire, so they're cached in memory for an hour
and never persisted). The browser loads the photo directly from Mapillary.
Licence: CC BY-SA 4.0. Attribution is shown with the image.
"""

import logging
import math
import threading
import time

import httpx

from app.core.streetview_urls import initial_bearing

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.mapillary.com"
ATTRIBUTION = "© Mapillary contributors · CC BY-SA 4.0"
THUMB_TTL_S = 3600
SEARCH_RADIUS_M = 60
MAX_FACING_OFF_DEG = 75  # camera must point roughly at the house


class MapillaryError(Exception):
    """Mapillary refused or failed the request (bad token, rate limit, outage)."""


def _distance_m(lat1, lng1, lat2, lng2) -> float:
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6_371_000 * math.hypot(dlat, dlng)


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def best_image(images: list[dict], lat: float, lng: float) -> str | None:
    """Closest image that faces the property; score = metres + 0.3 x degrees off-axis."""
    best, best_score = None, math.inf
    for img in images:
        if img.get("is_pano"):
            continue  # equirectangular panoramas look broken as a flat photo
        coords = (img.get("computed_geometry") or img.get("geometry") or {}).get("coordinates")
        angle = img.get("computed_compass_angle", img.get("compass_angle"))
        if not coords or angle is None:
            continue
        ilng, ilat = coords[0], coords[1]
        dist = _distance_m(ilat, ilng, lat, lng)
        if dist > SEARCH_RADIUS_M or dist < 3:
            continue
        off = angle_diff(float(angle), initial_bearing(ilat, ilng, lat, lng))
        if off > MAX_FACING_OFF_DEG:
            continue
        score = dist + 0.3 * off
        if score < best_score:
            best, best_score = str(img["id"]), score
    return best


def search_image(http: httpx.Client, lat: float, lng: float, token: str) -> str | None:
    """ID of the best nearby image facing (lat, lng), or None. Raises MapillaryError."""
    dlat = SEARCH_RADIUS_M / 111_320
    dlng = dlat / max(0.01, math.cos(math.radians(lat)))
    bbox = f"{lng - dlng:.6f},{lat - dlat:.6f},{lng + dlng:.6f},{lat + dlat:.6f}"
    try:
        resp = http.get(
            f"{GRAPH_URL}/images",
            params={
                "bbox": bbox,
                "fields": "id,computed_geometry,computed_compass_angle,is_pano",
                "limit": 50,
            },
            headers={"Authorization": f"OAuth {token}"},
        )
    except httpx.HTTPError as e:
        raise MapillaryError(f"Mapillary request failed: {type(e).__name__}") from e
    if resp.status_code != 200:
        raise MapillaryError(f"Mapillary returned HTTP {resp.status_code}")
    return best_image(resp.json().get("data", []), lat, lng)


class ThumbResolver:
    def __init__(self, transport: httpx.BaseTransport | None = None, ttl_s: float = THUMB_TTL_S):
        self._http = httpx.Client(timeout=5, transport=transport)
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()
        self.ttl_s = ttl_s

    def find(self, lat: float, lng: float, token: str) -> str | None:
        """Live image search for one home (used when a round is served). Raises MapillaryError."""
        return search_image(self._http, lat, lng, token)

    def thumb_url(self, image_id: str, token: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(image_id)
            if hit and now - hit[0] < self.ttl_s:
                return hit[1]
        url = None
        try:
            resp = self._http.get(
                f"{GRAPH_URL}/{image_id}",
                params={"fields": "thumb_1024_url"},
                headers={"Authorization": f"OAuth {token}"},
            )
            if resp.status_code == 200:
                url = resp.json().get("thumb_1024_url")
            else:
                log.warning("Mapillary thumbnail lookup returned HTTP %s", resp.status_code)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Mapillary thumbnail lookup failed: %s", type(e).__name__)
        with self._lock:
            self._cache[image_id] = (now, url)
            if len(self._cache) > 5000:
                for k in sorted(self._cache, key=lambda k: self._cache[k][0])[:1000]:
                    self._cache.pop(k, None)
        return url

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


resolver = ThumbResolver()
