"""Mapillary image check at ingestion (owner change 2026-11-27, see GDD Section 7.5).

For each unchecked property, ask Mapillary's Graph API for non-panoramic images within ~60 m,
then pick the one that is close AND whose camera points at the house. Only the image ID is
stored (`mly_image_id`, `mly_status`); the photo itself loads from Mapillary at play time.
"""

import logging
import math
import time
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.mapillary import GRAPH_URL
from app.core.streetview_urls import initial_bearing
from app.models import Property

log = logging.getLogger(__name__)

SEARCH_RADIUS_M = 60
MAX_FACING_OFF_DEG = 75  # camera must point roughly at the house
MIN_INTERVAL_S = 0.1


class MapillaryCheckError(Exception):
    """Mapillary refused the request (bad token, rate limit…). Stop; don't mark anything."""


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


class MapillaryChecker:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        if not token:
            raise MapillaryCheckError("MAPILLARY_TOKEN is not set")
        self._http = httpx.Client(
            timeout=20, transport=transport, headers={"Authorization": f"OAuth {token}"}
        )
        self._sleep = sleep or time.sleep

    def close(self) -> None:
        self._http.close()

    def lookup(self, lat: float, lng: float) -> str | None:
        dlat = SEARCH_RADIUS_M / 111_320
        dlng = dlat / max(0.01, math.cos(math.radians(lat)))
        bbox = f"{lng - dlng:.6f},{lat - dlat:.6f},{lng + dlng:.6f},{lat + dlat:.6f}"
        resp = self._http.get(
            f"{GRAPH_URL}/images",
            params={
                "bbox": bbox,
                "fields": "id,computed_geometry,computed_compass_angle,is_pano",
                "limit": 50,
            },
        )
        if resp.status_code != 200:
            raise MapillaryCheckError(f"Mapillary returned HTTP {resp.status_code}")
        return best_image(resp.json().get("data", []), lat, lng)

    def run(self, db: Session, limit: int = 500) -> dict[str, int]:
        props = (
            db.execute(
                select(Property)
                .where(
                    Property.mly_status == "unchecked",
                    Property.is_active.is_(True),
                    Property.location_precision.in_(("exact", "street")),
                )
                .order_by(Property.created_at)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        counts = {"ok": 0, "none": 0}
        try:
            for i, p in enumerate(props):
                if i:
                    self._sleep(MIN_INTERVAL_S)
                image_id = self.lookup(p.lat, p.lng)
                p.mly_image_id = image_id
                p.mly_status = "ok" if image_id else "none"
                counts[p.mly_status] += 1
                if i % 100 == 99:
                    db.commit()
        finally:
            db.commit()
        return counts
