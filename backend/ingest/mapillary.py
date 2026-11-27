"""Bulk Mapillary check (`python -m ingest mapillary-check`). Optional: the game also checks
unchecked homes on the fly when a round is served. Only the image ID is stored."""

import logging
import time
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.mapillary import (  # noqa: F401  (re-exported for tests)
    MAX_FACING_OFF_DEG,
    SEARCH_RADIUS_M,
    MapillaryError,
    angle_diff,
    best_image,
    search_image,
)
from app.models import Property

log = logging.getLogger(__name__)

MIN_INTERVAL_S = 0.1


class MapillaryCheckError(Exception):
    """Mapillary refused the request (bad token, rate limit). Stop; don't mark anything."""


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
        self.token = token
        self._http = httpx.Client(timeout=20, transport=transport)
        self._sleep = sleep or time.sleep

    def close(self) -> None:
        self._http.close()

    def lookup(self, lat: float, lng: float) -> str | None:
        try:
            return search_image(self._http, lat, lng, self.token)
        except MapillaryError as e:
            raise MapillaryCheckError(str(e)) from e

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
