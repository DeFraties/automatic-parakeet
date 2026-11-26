"""GET /api/meta — everything the UI needs to render the Home screen settings."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROUNDS_PER_GAME, get_settings
from app.core.countries import COUNTRIES, REGIONS, countries_in_region
from app.core.db import get_db
from app.core.selection import eligible_counts
from app.models import Source

router = APIRouter()


def daily_number(today: date, launch: date) -> int:
    """Day count since launch (launch day = #1)."""
    return (today - launch).days + 1


def _counts(urban: int, suburban: int, min_pool: int) -> dict:
    total = urban + suburban
    return {
        "eligible": {"urban": urban, "suburban": suburban, "total": total},
        "selectable": total >= max(min_pool, ROUNDS_PER_GAME),
    }


@router.get("/meta")
def meta(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    today = date.today()
    counts = eligible_counts(db, today=today, max_age_years=s.max_price_age_years)
    mp = s.min_pool_per_option

    def cc_counts(code: str) -> tuple[int, int]:
        c = counts.get(code, {})
        return c.get("urban", 0), c.get("suburban", 0)

    countries = [
        {
            "code": c.code,
            "name": c.name,
            "flag": c.flag,
            "currency": c.currency,
            "currency_name": c.currency_name,
            "region": c.region,
            "locale": c.locale,
            **_counts(*cc_counts(c.code), mp),
        }
        for c in COUNTRIES
    ]
    regions = []
    for r in REGIONS:
        members = countries_in_region(r.key)
        u = sum(cc_counts(c.code)[0] for c in members)
        sub = sum(cc_counts(c.code)[1] for c in members)
        regions.append(
            {"key": r.key, "name": r.name, "countries": [c.code for c in members]}
            | _counts(u, sub, mp)
        )
    wu = sum(v.get("urban", 0) for v in counts.values())
    ws = sum(v.get("suburban", 0) for v in counts.values())
    world = _counts(wu, ws, 0)  # World only needs enough for one game

    sources = db.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
    return {
        "countries": countries,
        "regions": regions,
        "world": world,
        "sources": [
            {
                "key": src.key,
                "display_name": src.display_name,
                "homepage": src.homepage,
                "license_note": src.license_note,
            }
            for src in sources
        ],
        "daily_number": daily_number(today, s.launch_date),
        "min_pool_per_option": mp,
        "rounds_per_game": ROUNDS_PER_GAME,
        "public_base_url": s.public_base_url,
        "contact_email": s.contact_email,
        "quota": {"games_available": True},
    }
