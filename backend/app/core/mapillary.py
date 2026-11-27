"""Mapillary street-level imagery at play time (Section 7, owner change 2026-11-27).

Only the Mapillary image ID is stored. At round time the server asks Mapillary's Graph API for
the image's current thumbnail URL (these CDN URLs expire, so they're cached in memory for an hour
and never persisted). The browser loads the photo directly from Mapillary.
Licence: CC BY-SA 4.0. Attribution is shown with the image.
"""

import threading
import time

import httpx

GRAPH_URL = "https://graph.mapillary.com"
ATTRIBUTION = "© Mapillary contributors · CC BY-SA 4.0"
THUMB_TTL_S = 3600


class ThumbResolver:
    def __init__(self, transport: httpx.BaseTransport | None = None, ttl_s: float = THUMB_TTL_S):
        self._http = httpx.Client(timeout=5, transport=transport)
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()
        self.ttl_s = ttl_s

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
        except (httpx.HTTPError, ValueError):
            url = None
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
