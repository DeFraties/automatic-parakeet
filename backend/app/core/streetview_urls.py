"""Street View Static API URL building (Section 7.3).

Phase 1 ships the pure helpers (heading + URL signing). Wiring the live metadata lookup and the
quota counter happens in Phase 3; until then rounds use a placeholder image.
"""

import base64
import hashlib
import hmac
import math
from urllib.parse import urlencode, urlparse

STREETVIEW_BASE = "https://maps.googleapis.com/maps/api/streetview"
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


def build_streetview_url(pano_id: str, heading: float, api_key: str, secret_b64: str) -> str:
    query = urlencode(
        {
            "size": "640x640",
            "pano": pano_id,
            "heading": f"{heading:.1f}",
            "pitch": 5,
            "fov": 80,
            "key": api_key,
        }
    )
    return sign_url(f"{STREETVIEW_BASE}?{query}", secret_b64)
