"""Listing photos at play time (Section 4.2 / 7). Only URLs are handled here, never image bytes:
the player's browser loads every photo straight from the listing site."""

from sqlalchemy import and_, exists, func, select

from app.core.config import get_settings
from app.models import PhotoReport, Property, PropertyImage, utcnow


def ok_photo_count():
    """Correlated subquery: number of `ok` photos for the outer Property row."""
    return (
        select(func.count())
        .where(PropertyImage.property_id == Property.id, PropertyImage.status == "ok")
        .scalar_subquery()
    )


def open_price_report():
    """True if a player reported the price as visible in a photo and nobody reviewed it yet."""
    return exists().where(
        and_(
            PhotoReport.property_id == Property.id,
            PhotoReport.reason == "price_visible",
            PhotoReport.status == "open",
        )
    )


def ordered_ok_images(p: Property) -> list[PropertyImage]:
    """Listing order, with floor plans moved to the end (owner decision), capped per round."""
    ok = [i for i in p.images if i.status == "ok"]
    photos = [i for i in ok if i.kind != "floorplan"] + [i for i in ok if i.kind == "floorplan"]
    return photos[: get_settings().max_photos_per_round]


def round_photos(p: Property, place: str) -> list[dict]:
    imgs = ordered_ok_images(p)
    n = len(imgs)
    out = []
    for idx, img in enumerate(imgs):
        what = "Floor plan" if img.kind == "floorplan" else "Listing photo"
        out.append(
            {
                "position": img.position,
                "url": img.url,
                "width": img.width,
                "height": img.height,
                "kind": img.kind,
                "alt": f"{what} {idx + 1} of {n}, property in {place}",
            }
        )
    return out


def photo_credit(p: Property) -> str:
    return f"Photos: {p.source.display_name}"


def lead_photo_url(p: Property) -> str | None:
    imgs = ordered_ok_images(p)
    return imgs[0].url if imgs else None


def recompute_images_status(p: Property) -> str:
    ok = sum(1 for i in p.images if i.status == "ok")
    p.images_status = "ok" if ok >= get_settings().min_ok_photos else "broken"
    return p.images_status


def mark_broken(p: Property, positions: list[int]) -> None:
    """Client couldn't load these photos (Section 7.4)."""
    wanted = set(positions)
    for img in p.images:
        if img.position in wanted:
            img.status = "broken"
    recompute_images_status(p)
    p.images_checked_at = utcnow()
