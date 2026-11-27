"""Google Street View daily URL budget (Section 7.3 step 5).

`sv_usage.urls_issued` counts every signed URL issued on a UTC day; `daily_reserved_used` counts
the ones issued for Daily Challenge games. Non-daily games may use `GOOGLE_DAILY_QUOTA -
DAILY_RESERVED`; the Daily Challenge may use whatever is left of the full quota.
Without a Google key no URLs are issued, so the quota never blocks anything.
"""

from datetime import UTC, date, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import ROUNDS_PER_GAME, get_settings
from app.models import SvUsage


def utc_today() -> date:
    return datetime.now(UTC).date()


def _usage(db: Session, day: date) -> tuple[int, int]:
    row = db.get(SvUsage, day)
    return (row.urls_issued, row.daily_reserved_used) if row else (0, 0)


def google_enabled() -> bool:
    s = get_settings()
    return bool(s.google_maps_api_key and s.google_url_signing_secret)


def can_start_game(db: Session, *, daily: bool, day: date | None = None) -> bool:
    if not google_enabled():
        return True
    s = get_settings()
    issued, daily_used = _usage(db, day or utc_today())
    if daily:
        return issued + ROUNDS_PER_GAME <= s.google_daily_quota
    non_daily = issued - daily_used
    budget = max(0, s.google_daily_quota - s.daily_reserved)
    return (
        non_daily + ROUNDS_PER_GAME <= budget and issued + ROUNDS_PER_GAME <= s.google_daily_quota
    )


def record_url(db: Session, *, daily: bool, day: date | None = None) -> None:
    """Atomically count one issued URL (portable upsert: UPDATE, else INSERT, retry on race)."""
    day = day or utc_today()
    inc = {
        "urls_issued": SvUsage.urls_issued + 1,
        "daily_reserved_used": SvUsage.daily_reserved_used + (1 if daily else 0),
    }
    for _ in range(3):
        res = db.execute(update(SvUsage).where(SvUsage.date == day).values(**inc))
        if res.rowcount:
            db.commit()
            return
        try:
            db.add(SvUsage(date=day, urls_issued=1, daily_reserved_used=1 if daily else 0))
            db.commit()
            return
        except IntegrityError:
            db.rollback()


def status(db: Session) -> dict:
    return {
        "games_available": can_start_game(db, daily=False),
        "daily_available": can_start_game(db, daily=True),
    }
