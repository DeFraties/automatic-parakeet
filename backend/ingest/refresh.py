"""Refresh job (Section 8.7): re-check listings that haven't been seen for a while.

- Listing gone (404/410, or the plugin says delisted) -> is_active = false
- Still live -> last_seen_at updated, photo URLs re-synced and re-verified
- Asking-price listings gone for 30+ days are deleted with their photo URLs (kept as an inactive
  stub without photos if a past game still references them)
"""

import logging
from datetime import timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import GameRound, Property, utcnow
from ingest.http import PoliteClient, RobotsDisallowed, SourceBlocked
from ingest.images import ImageChecker, verify_property
from ingest.pipeline import sync_images
from ingest.sources.base import SourcePlugin

log = logging.getLogger(__name__)

GONE_DELETE_DAYS = 30


def run_refresh(
    db: Session,
    plugins: dict[str, SourcePlugin],
    client: PoliteClient,
    check: ImageChecker,
    *,
    older_than_days: int,
    limit: int,
) -> dict[str, int]:
    counts = {"checked": 0, "live": 0, "gone": 0, "skipped": 0, "deleted": 0}
    cutoff = utcnow() - timedelta(days=older_than_days)
    props = (
        db.execute(
            select(Property)
            .where(Property.is_active.is_(True), Property.last_seen_at < cutoff)
            .order_by(Property.last_seen_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    blocked: set[int] = set()
    for p in props:
        plugin = plugins.get(p.source.key)
        if plugin is None or not p.listing_url or p.source_id in blocked:
            counts["skipped"] += 1  # e.g. demo data has no plugin
            continue
        ref = plugin.refresh_ref(p.listing_url, p.source_ref)
        counts["checked"] += 1
        try:
            page = client.get(ref, use_cache=False)
            if page.status in (404, 410):
                listing = None
            elif page.status == 200:
                listing = plugin.fetch_and_parse(client, ref)  # served from the fresh cache
            else:
                counts["skipped"] += 1
                continue
            if listing is None:
                p.is_active = False
                counts["gone"] += 1
                log.info("[%s] delisted: %s", p.source.key, p.id)
            else:
                p.last_seen_at = utcnow()
                sync_images(db, p, listing)
                db.flush()
                verify_property(p, check, p.source.image_hosts or [])
                counts["live"] += 1
        except RobotsDisallowed:
            counts["skipped"] += 1
        except SourceBlocked as e:
            log.error("[%s] refresh stopped: %s", p.source.key, e)
            blocked.add(p.source_id)
            db.rollback()
            continue
        db.commit()
    counts["deleted"] = purge_gone_listings(db)
    return counts


def purge_gone_listings(db: Session, days: int = GONE_DELETE_DAYS) -> int:
    """Delete asking-price listings that have been gone for `days`+, with their photo URLs."""
    cutoff = utcnow() - timedelta(days=days)
    gone = (
        db.execute(
            select(Property).where(
                Property.is_active.is_(False),
                Property.price_type == "asking",
                Property.last_seen_at < cutoff,
            )
        )
        .scalars()
        .all()
    )
    n = 0
    for p in gone:
        p.images.clear()  # delete-orphan cascade removes the photo URL rows
        db.flush()
        referenced = db.execute(select(exists().where(GameRound.property_id == p.id))).scalar_one()
        if not referenced:
            db.delete(p)
        n += 1
    db.commit()
    return n
