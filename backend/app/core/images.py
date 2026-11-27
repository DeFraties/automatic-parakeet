"""Pick the image for a round (Section 7, owner change 2026-11-27).

Order: the source's own listing photo (hotlinked, credited) -> Google Street View (only when a
key is configured) -> Mapillary -> none (the client shows an illustrated card).
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import mapillary, quota
from app.core.config import get_settings
from app.core.streetview_urls import ATTRIBUTION as GOOGLE_ATTRIBUTION
from app.core.streetview_urls import image_for
from app.models import Property

IMAGE_SOURCES = ("listing", "google", "mapillary")
PRECISE = ("exact", "street")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoundImage:
    url: str | None
    source: str | None  # listing | google | mapillary | None
    attribution: str | None


NO_IMAGE = RoundImage(None, None, None)


def round_image(db: Session, p: Property, *, daily: bool) -> RoundImage:
    s = get_settings()
    if p.image_url:
        return RoundImage(p.image_url, "listing", f"Photo: {p.source.display_name}")
    if p.sv_status == "ok" and p.pano_id and quota.google_enabled():
        url = image_for(
            p.pano_id, p.lat, p.lng, api_key=s.google_maps_api_key,
            secret=s.google_url_signing_secret,
        )  # fmt: skip
        if url:
            quota.record_url(db, daily=daily)
            return RoundImage(url, "google", GOOGLE_ATTRIBUTION)
    if s.mapillary_token and p.mly_status == "unchecked" and p.location_precision in PRECISE:
        # Not checked yet (e.g. `ingest mapillary-check` never ran): look it up now and save
        # the result, so photos appear as soon as a token is configured.
        try:
            image_id = mapillary.resolver.find(p.lat, p.lng, s.mapillary_token)
            p.mly_image_id, p.mly_status = image_id, ("ok" if image_id else "none")
            db.commit()
        except mapillary.MapillaryError as e:
            log.warning("Mapillary check for property %s failed: %s", p.id, e)
    if p.mly_status == "ok" and p.mly_image_id and s.mapillary_token:
        url = mapillary.resolver.thumb_url(p.mly_image_id, s.mapillary_token)
        if url:
            return RoundImage(url, "mapillary", mapillary.ATTRIBUTION)
    return NO_IMAGE


def forget_broken(p: Property, source: str) -> None:
    """A player's browser couldn't load this image: never deletes the home, only the link.

    listing   -> drop the photo URL (the next ingest run restores it if it's still valid)
    google    -> back to 'unchecked' for `ingest streetview-check`
    mapillary -> back to 'unchecked' for `ingest mapillary-check`
    """
    if source == "listing":
        p.image_url = None
    elif source == "google" and p.sv_status == "ok":
        p.sv_status = "unchecked"
    elif source == "mapillary" and p.mly_status == "ok":
        p.mly_status = "unchecked"
