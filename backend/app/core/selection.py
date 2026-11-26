"""Round selection: eligibility (Section 5.3) and pool balancing (Section 5.4)."""

import math
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.core.config import ELIGIBLE_USD_MAX, ELIGIBLE_USD_MIN, ROUNDS_PER_GAME
from app.core.countries import COUNTRY_CODES, countries_in_region
from app.models import Blocklist, Property

SETTING_FILTERS: dict[str, tuple[str, ...]] = {
    "urban_suburban": ("urban", "suburban"),
    "urban": ("urban",),
    "suburban": ("suburban",),
}

MAX_PER_COUNTRY = 2
MIN_QUINTILES = 3
MIN_EACH_SETTING = 2  # urban + suburban mix in default games
ATTEMPTS_PER_LEVEL = 200


class PoolTooSmall(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    id: str
    country_code: str
    city: str
    setting: str
    price_usd: float


def _years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - years, day=28)


def eligibility_clauses(today: date, max_age_years: int, setting_filter: str = "urban_suburban"):
    """SQLAlchemy WHERE clauses for a playable property."""
    blocked = exists().where(
        and_(Blocklist.source_id == Property.source_id, Blocklist.source_ref == Property.source_ref)
    )
    return [
        Property.is_active.is_(True),
        Property.sv_status == "ok",
        Property.country_code.in_(sorted(COUNTRY_CODES)),
        Property.location_precision.in_(("exact", "street")),
        Property.price_usd >= ELIGIBLE_USD_MIN,
        Property.price_usd <= ELIGIBLE_USD_MAX,
        Property.price_date >= _years_ago(today, max_age_years),
        Property.setting.in_(SETTING_FILTERS[setting_filter]),
        ~blocked,
    ]


def scope_clause(where_scope: str, where_value: str | None):
    if where_scope == "country" and where_value:
        return Property.country_code == where_value.upper()
    if where_scope == "region" and where_value:
        return Property.country_code.in_([c.code for c in countries_in_region(where_value)])
    return None


def load_candidates(
    db: Session,
    *,
    today: date,
    max_age_years: int,
    setting_filter: str,
    where_scope: str = "world",
    where_value: str | None = None,
) -> list[Candidate]:
    clauses = eligibility_clauses(today, max_age_years, setting_filter)
    sc = scope_clause(where_scope, where_value)
    if sc is not None:
        clauses.append(sc)
    rows = db.execute(
        select(
            Property.id, Property.country_code, Property.city, Property.setting, Property.price_usd
        ).where(*clauses)
    ).all()
    return [Candidate(*r) for r in rows]


def eligible_counts(db: Session, *, today: date, max_age_years: int) -> dict[str, dict[str, int]]:
    """{country_code: {"urban": n, "suburban": n}} for all playable properties."""
    rows = db.execute(
        select(Property.country_code, Property.setting, func.count())
        .where(*eligibility_clauses(today, max_age_years, "urban_suburban"))
        .group_by(Property.country_code, Property.setting)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for cc, setting, n in rows:
        out.setdefault(cc, {"urban": 0, "suburban": 0})[setting] = n
    return out


def price_quintiles(cands: list[Candidate]) -> dict[str, int]:
    """Map candidate id -> log-price quintile (0..4) within the given pool."""
    ordered = sorted(cands, key=lambda c: math.log(c.price_usd))
    n = len(ordered)
    return {c.id: min(4, i * 5 // n) for i, c in enumerate(ordered)} if n else {}


@dataclass(frozen=True)
class _Rules:
    unique_city: bool = True
    country_cap: bool = True
    quintile_spread: bool = True
    setting_mix: bool = True


# Progressive relaxation when the pool can't satisfy every rule.
_RELAXATION = (
    _Rules(),
    _Rules(setting_mix=False),
    _Rules(setting_mix=False, quintile_spread=False),
    _Rules(setting_mix=False, quintile_spread=False, unique_city=False),
    _Rules(setting_mix=False, quintile_spread=False, unique_city=False, country_cap=False),
)


def pick_rounds(
    cands: list[Candidate],
    *,
    rng: random.Random,
    where_scope: str = "world",
    setting_filter: str = "urban_suburban",
    min_pool_per_country: int = 50,
    n: int = ROUNDS_PER_GAME,
) -> list[Candidate]:
    """Choose `n` properties following the pool-balancing rules. Deterministic for a given rng."""
    if len(cands) < n:
        raise PoolTooSmall(f"only {len(cands)} eligible properties")

    cands = sorted(cands, key=lambda c: c.id)  # stable order => deterministic with a seeded rng
    quint = price_quintiles(cands)
    pool_quintiles = len(set(quint.values()))
    settings_avail = Counter(c.setting for c in cands)
    by_country: dict[str, list[Candidate]] = {}
    for c in cands:
        by_country.setdefault(c.country_code, []).append(c)

    world = where_scope != "country"
    use_country_weighting = where_scope == "world"
    # Countries eligible for equal-weight selection. If too few meet the threshold (e.g., small
    # dev/seed databases), fall back to every country with eligible properties.
    weighted = sorted(cc for cc, lst in by_country.items() if len(lst) >= min_pool_per_country)
    if len(weighted) * MAX_PER_COUNTRY < n:
        weighted = sorted(by_country)

    cities_in_pool = len({(c.country_code, c.city) for c in cands})

    for rules in _RELAXATION:
        enforce_city = rules.unique_city and not (where_scope == "country" and cities_in_pool < n)
        enforce_cap = rules.country_cap and world
        need_quint = rules.quintile_spread and pool_quintiles >= MIN_QUINTILES
        need_mix = (
            rules.setting_mix
            and setting_filter == "urban_suburban"
            and settings_avail["urban"] >= MIN_EACH_SETTING
            and settings_avail["suburban"] >= MIN_EACH_SETTING
        )

        for _ in range(ATTEMPTS_PER_LEVEL):
            picks = _attempt(
                cands,
                by_country,
                weighted,
                rng,
                n,
                use_country_weighting,
                enforce_city,
                enforce_cap,
            )
            if picks is None:
                continue
            if need_quint and len({quint[p.id] for p in picks}) < MIN_QUINTILES:
                continue
            if need_mix:
                s = Counter(p.setting for p in picks)
                if s["urban"] < MIN_EACH_SETTING or s["suburban"] < MIN_EACH_SETTING:
                    continue
            rng.shuffle(picks)
            return picks

    raise PoolTooSmall("could not build a game from the pool")  # pragma: no cover


def _attempt(
    cands: list[Candidate],
    by_country: dict[str, list[Candidate]],
    weighted: list[str],
    rng: random.Random,
    n: int,
    use_country_weighting: bool,
    enforce_city: bool,
    enforce_cap: bool,
) -> list[Candidate] | None:
    """One randomized attempt at filling `n` slots under the hard per-slot rules."""
    picks: list[Candidate] = []
    used_ids: set[str] = set()
    used_cities: set[tuple[str, str]] = set()
    per_country: Counter[str] = Counter()

    def ok(c: Candidate) -> bool:
        if c.id in used_ids:
            return False
        if enforce_city and (c.country_code, c.city) in used_cities:
            return False
        return not (enforce_cap and per_country[c.country_code] >= MAX_PER_COUNTRY)

    for _slot in range(n):
        if use_country_weighting:
            # Pick a country first (equal weight), then a property within it.
            countries = [cc for cc in weighted if any(ok(c) for c in by_country[cc])]
            if not countries:
                countries = [cc for cc in sorted(by_country) if any(ok(c) for c in by_country[cc])]
            if not countries:
                return None
            options = [c for c in by_country[rng.choice(countries)] if ok(c)]
        else:
            options = [c for c in cands if ok(c)]
        if not options:
            return None
        c = rng.choice(options)
        picks.append(c)
        used_ids.add(c.id)
        used_cities.add((c.country_code, c.city))
        per_country[c.country_code] += 1
    return picks
