"""Daily Challenge generation (Section 6.3): same 5 properties for everyone on a UTC date."""

import hashlib
import logging
import random
from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.selection import (
    DEFAULT_SETTING_FILTER,
    PoolTooSmall,
    load_candidates,
    pick_rounds,
    recently_verified,
)
from app.models import DailyChallenge, Property, utcnow

log = logging.getLogger(__name__)

# Daily is always World with the default setting mix; difficulty is the player's choice.
DAILY_WHERE_SCOPE = "world"
DAILY_SETTING_FILTER = DEFAULT_SETTING_FILTER


def utc_today() -> date:
    return datetime.now(UTC).date()


# Re-checks a property's photo URLs right before the Daily is saved (Section 6.3). Returns True if
# it still has enough working photos. Set by the API app (`ingest.images`); None = don't check.
PhotoVerifier = Callable[[Session, Property], bool]
photo_verifier: PhotoVerifier | None = None


def daily_seed(day: date, salt: str) -> int:
    return int(hashlib.sha256(f"{day.isoformat()}{salt}".encode()).hexdigest(), 16)


def daily_number(day: date, launch: date) -> int:
    """#1 on launch day. Clamped to 1 before launch so the share text never shows #0 or less."""
    return max(1, (day - launch).days + 1)


MAX_REPLACEMENTS = 10


def generate_ids(db: Session, day: date, verify: PhotoVerifier | None = None) -> list[str]:
    """Pick the day's 5 homes. Prefers homes whose photos were verified in the last 48 hours,
    re-verifies the picks, and replaces any whose photos no longer load."""
    s = get_settings()
    rng = random.Random(daily_seed(day, s.daily_salt))
    cands = load_candidates(
        db,
        today=day,
        max_age_years=s.max_price_age_years,
        setting_filter=DAILY_SETTING_FILTER,
        where_scope=DAILY_WHERE_SCOPE,
    )
    rejected: set[str] = set()
    for _ in range(MAX_REPLACEMENTS + 1):
        pool = [c for c in cands if c.id not in rejected]
        fresh = recently_verified(pool, utcnow())
        picks = None
        for candidate_pool in (fresh, pool):
            try:
                picks = pick_rounds(
                    candidate_pool,
                    rng=random.Random(rng.random()),
                    where_scope=DAILY_WHERE_SCOPE,
                    setting_filter=DAILY_SETTING_FILTER,
                    min_pool_per_country=s.min_pool_per_option,
                )
                break
            except PoolTooSmall:
                continue
        if picks is None:
            raise PoolTooSmall("not enough properties for a Daily Challenge")
        if verify is None:
            return [p.id for p in picks]
        failed = [p.id for p in picks if not verify(db, db.get(Property, p.id))]
        if not failed:
            return [p.id for p in picks]
        log.info("daily %s: %d picks failed photo re-check, replacing", day, len(failed))
        rejected.update(failed)
    raise PoolTooSmall("too many Daily picks failed the photo re-check")


def get_or_create(db: Session, day: date) -> DailyChallenge:
    """Lazily create today's challenge. The date primary key acts as the lock: if two workers race,
    the second insert fails and it reads the first one's row. Raises PoolTooSmall."""
    row = db.get(DailyChallenge, day)
    if row is not None:
        return row
    ids = generate_ids(db, day, verify=photo_verifier)
    try:
        db.add(DailyChallenge(date=day, property_ids=ids))
        db.commit()
        log.info("generated daily challenge for %s", day)
    except IntegrityError:
        db.rollback()
    return db.get(DailyChallenge, day)
