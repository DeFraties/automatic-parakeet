"""GET /api/meta — everything the UI needs to render the Home screen settings."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROUNDS_PER_GAME, get_settings
from app.core.countries import COUNTRIES, REGIONS, countries_in_region
from app.core.daily import daily_number, utc_today
from app.core.db import get_db
from app.core.selection import ALL_SETTINGS, DEFAULT_SETTINGS, eligible_counts
from app.models import Source

router = APIRouter()


def _counts(by_setting: dict[str, int], min_pool: int) -> dict:
    """Per-setting eligible counts. `selectable` is for the default setting mix; the client
    recomputes it for whatever toggles the player has chosen."""
    default_total = sum(by_setting.get(x, 0) for x in DEFAULT_SETTINGS)
    return {
        "eligible": {x: by_setting.get(x, 0) for x in ALL_SETTINGS},
        "selectable": default_total >= max(min_pool, ROUNDS_PER_GAME),
    }


@router.get("/meta")
def meta(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    today = date.today()
    counts = eligible_counts(db, today=today, max_age_years=s.max_price_age_years)
    mp = s.min_pool_per_option

    def cc_counts(code: str) -> dict[str, int]:
        return counts.get(code, {})

    def summed(codes) -> dict[str, int]:
        return {x: sum(cc_counts(c).get(x, 0) for c in codes) for x in ALL_SETTINGS}

    countries = [
        {
            "code": c.code,
            "name": c.name,
            "flag": c.flag,
            "currency": c.currency,
            "currency_name": c.currency_name,
            "region": c.region,
            "locale": c.locale,
            **_counts(cc_counts(c.code), mp),
        }
        for c in COUNTRIES
    ]
    regions = []
    for r in REGIONS:
        members = [c.code for c in countries_in_region(r.key)]
        regions.append(
            {"key": r.key, "name": r.name, "emoji": r.emoji, "countries": members}
            | _counts(summed(members), mp)
        )
    world = _counts(summed(counts), 0)  # World only needs enough for one game

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
                "image_hosts": src.image_hosts or [],
            }
            for src in sources
        ],
        "daily_number": daily_number(utc_today(), s.launch_date),
        "settings": {"all": list(ALL_SETTINGS), "default": list(DEFAULT_SETTINGS)},
        "tile_url": s.osm_tile_url,
        "tile_attribution": s.tile_attribution,
        "min_pool_per_option": mp,
        "rounds_per_game": ROUNDS_PER_GAME,
        "public_base_url": s.public_base_url,
        "contact_email": s.contact_email,
    }
