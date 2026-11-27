"""Daily Challenge generation (Section 6.3): same 5 properties for everyone on a UTC date."""

import hashlib
import logging
import random
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.selection import DEFAULT_SETTING_FILTER, load_candidates, pick_rounds
from app.models import DailyChallenge

log = logging.getLogger(__name__)

# Daily is always World with the default setting mix; difficulty is the player's choice.
DAILY_WHERE_SCOPE = "world"
DAILY_SETTING_FILTER = DEFAULT_SETTING_FILTER


def daily_seed(day: date, salt: str) -> int:
    return int(hashlib.sha256(f"{day.isoformat()}{salt}".encode()).hexdigest(), 16)


def daily_number(day: date, launch: date) -> int:
    """#1 on launch day. Clamped to 1 before launch so the share text never shows #0 or less."""
    return max(1, (day - launch).days + 1)


def generate_ids(db: Session, day: date) -> list[str]:
    s = get_settings()
    cands = load_candidates(
        db,
        today=day,
        max_age_years=s.max_price_age_years,
        setting_filter=DAILY_SETTING_FILTER,
        where_scope=DAILY_WHERE_SCOPE,
    )
    picks = pick_rounds(
        cands,
        rng=random.Random(daily_seed(day, s.daily_salt)),
        where_scope=DAILY_WHERE_SCOPE,
        setting_filter=DAILY_SETTING_FILTER,
        min_pool_per_country=s.min_pool_per_option,
    )
    return [p.id for p in picks]


def get_or_create(db: Session, day: date) -> DailyChallenge:
    """Lazily create today's challenge. The date primary key acts as the lock: if two workers race,
    the second insert fails and it reads the first one's row. Raises PoolTooSmall."""
    row = db.get(DailyChallenge, day)
    if row is not None:
        return row
    ids = generate_ids(db, day)
    try:
        db.add(DailyChallenge(date=day, property_ids=ids))
        db.commit()
        log.info("generated daily challenge for %s", day)
    except IntegrityError:
        db.rollback()
    return db.get(DailyChallenge, day)
