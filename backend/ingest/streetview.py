"""Street View availability check at ingestion (Section 7.2).

Calls Google's free metadata endpoint for each unchecked property. Stores ONLY `pano_id` and
`sv_status`; the metadata's own location/date are not kept (Compliance rule 2).
"""

import logging
import time
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.streetview_urls import METADATA_URL
from app.models import Property

log = logging.getLogger(__name__)

NO_IMAGERY = {"ZERO_RESULTS", "NOT_FOUND"}
MIN_INTERVAL_S = 0.05  # stay far below Google's per-second limits


class StreetViewCheckError(Exception):
    """Google refused the request (bad key, quota, …). Stop; don't mark anything."""


class StreetViewChecker:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        if not api_key:
            raise StreetViewCheckError("GOOGLE_MAPS_API_KEY is not set")
        self.api_key = api_key
        self._http = httpx.Client(timeout=15, transport=transport)
        self._sleep = sleep or time.sleep

    def close(self) -> None:
        self._http.close()

    def lookup(self, lat: float, lng: float) -> str | None:
        """pano_id if outdoor imagery exists within 50 m, else None."""
        resp = self._http.get(
            METADATA_URL,
            params={"location": f"{lat:.6f},{lng:.6f}", "radius": 50, "source": "outdoor",
                    "key": self.api_key},
        )  # fmt: skip
        if resp.status_code != 200:
            raise StreetViewCheckError(f"metadata endpoint returned HTTP {resp.status_code}")
        data = resp.json()
        status = data.get("status")
        if status == "OK" and data.get("pano_id"):
            return data["pano_id"]
        if status in NO_IMAGERY:
            return None
        raise StreetViewCheckError(f"metadata status {status}: {data.get('error_message', '')}")

    def run(self, db: Session, limit: int = 500) -> dict[str, int]:
        props = (
            db.execute(
                select(Property)
                .where(
                    Property.sv_status == "unchecked",
                    Property.is_active.is_(True),
                    # district-level records are never playable: don't spend calls on them
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
                pano = self.lookup(p.lat, p.lng)
                p.pano_id = pano
                p.sv_status = "ok" if pano else "none"
                counts[p.sv_status] += 1
                if i % 100 == 99:
                    db.commit()
        finally:
            db.commit()
        return counts
