"""Photo URL verification (Section 7.2) and the Daily Challenge re-check (Section 6.3).

Only status codes and content types are looked at: image bytes are never read, cached or stored.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.photos import recompute_images_status
from app.models import Property, utcnow
from ingest.http import PoliteClient, RobotsDisallowed, SourceBlocked
from ingest.validate import image_host_allowed

log = logging.getLogger(__name__)

ImageChecker = Callable[[str], bool]


def is_local_demo(url: str) -> bool:
    """Seed data uses our own placeholder illustrations (/demo-photos/...), never checked."""
    return url.startswith("/demo-photos/")


def verify_property(p: Property, check: ImageChecker, allowed_hosts: list[str]) -> str:
    """Re-check every photo URL of a property and update its images_status (ok if >= 2 work)."""
    for img in p.images:
        if is_local_demo(img.url):
            img.status = "ok"
            continue
        if not image_host_allowed(img.url, allowed_hosts):
            img.status = "broken"
            continue
        try:
            img.status = "ok" if check(img.url) else "broken"
        except RobotsDisallowed:
            img.status = "broken"
    p.images_checked_at = utcnow()
    return recompute_images_status(p)


def client_checker(client: PoliteClient, delay: float = 1.0) -> ImageChecker:
    return lambda url: client.check_image(url, delay=delay)


def run_images_check(
    db: Session, client: PoliteClient, *, limit: int = 500, stale_days: int | None = None
) -> dict[str, int]:
    """Verify unchecked properties, and those not checked for `stale_days` (REFRESH_DAYS)."""
    stale_days = get_settings().refresh_days if stale_days is None else stale_days
    cutoff = utcnow() - timedelta(days=stale_days)
    props = (
        db.execute(
            select(Property)
            .where(
                Property.is_active.is_(True),
                or_(
                    Property.images_status == "unchecked",
                    Property.images_checked_at.is_(None),
                    Property.images_checked_at < cutoff,
                ),
            )
            .order_by(Property.images_checked_at.is_not(None), Property.images_checked_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    counts = {"ok": 0, "broken": 0, "blocked_sources": 0}
    blocked: set[int] = set()
    check = client_checker(client)
    for p in props:
        if p.source_id in blocked:
            continue
        try:
            status = verify_property(p, check, p.source.image_hosts or [])
        except SourceBlocked as e:
            log.error("[%s] image checks stopped: %s", p.source.key, e)
            blocked.add(p.source_id)
            counts["blocked_sources"] += 1
            db.rollback()
            continue
        counts[status] += 1
        db.commit()
    return counts


def daily_photo_verifier(db: Session, p: Property) -> bool:
    """Used by the API right before saving a Daily Challenge."""
    if all(is_local_demo(i.url) for i in p.images):
        return p.images_status == "ok"
    s = get_settings()
    client = PoliteClient(s.scraper_user_agent, Path(s.ingest_cache_dir))
    try:
        status = verify_property(p, client_checker(client), p.source.image_hosts or [])
    except SourceBlocked:
        status = "broken"
    finally:
        client.close()
    db.commit()
    return status == "ok"
