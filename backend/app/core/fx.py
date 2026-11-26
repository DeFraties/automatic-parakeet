"""FX lookups at play time. (Ingestion-time FX fetching lives in `ingest/fx.py`, Phase 2.)"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FxRate

_cache: dict[tuple[date, str], float | None] = {}


def latest_rate(db: Session, currency: str, today: date | None = None) -> float | None:
    """Most recent stored USD-per-unit rate for `currency`, cached in memory per UTC day."""
    if currency == "USD":
        return 1.0
    today = today or date.today()
    key = (today, currency)
    if key not in _cache:
        _cache[key] = db.execute(
            select(FxRate.rate_to_usd)
            .where(FxRate.currency == currency, FxRate.date <= today)
            .order_by(FxRate.date.desc())
            .limit(1)
        ).scalar_one_or_none()
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()
