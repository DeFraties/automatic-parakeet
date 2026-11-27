"""Round selection: eligibility (Section 5.3) and pool balancing (Section 5.4)."""

import math
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.core.config import ELIGIBLE_USD_MAX, ELIGIBLE_USD_MIN, ROUNDS_PER_GAME, get_settings
from app.core.countries import COUNTRY_CODES, countries_in_region
from app.core.photos import ok_photo_count, open_price_report
from app.models import Blocklist, Property

# Owner decision (2026-11-27): two neighbourhood categories. Suburbs count as urban.
ALL_SETTINGS: tuple[str, ...] = ("urban", "rural")
DEFAULT_SETTINGS: tuple[str, ...] = ("urban", "rural")


def encode_settings(settings) -> str:
    """Canonical storage form of a setting selection, e.g. ["urban", "rural"] -> "rural,urban"."""
    chosen = sorted(set(settings))
    if not chosen or any(x not in ALL_SETTINGS for x in chosen):
        raise ValueError(f"settings must be a non-empty subset of {ALL_SETTINGS}")
    return ",".join(chosen)


def decode_settings(encoded: str) -> tuple[str, ...]:
    return tuple(x for x in encoded.split(",") if x)


DEFAULT_SETTING_FILTER = encode_settings(DEFAULT_SETTINGS)

MAX_PER_COUNTRY = 2
MAX_PER_SOURCE = 3
MIN_QUINTILES = 3
MIN_EACH_SETTING = 2  # with both settings selected: >= 2 rounds of each
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
    source_id: int = 0
    images_checked_at: datetime | None = None


def _years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - years, day=28)


def eligibility_clauses(
    today: date, max_age_years: int, setting_filter: str = DEFAULT_SETTING_FILTER
):
    """SQLAlchemy WHERE clauses for a playable property (Section 5.3)."""
    blocked = exists().where(
        and_(Blocklist.source_id == Property.source_id, Blocklist.source_ref == Property.source_ref)
    )
    return [
        Property.is_active.is_(True),
        Property.images_status == "ok",
        ok_photo_count() >= get_settings().min_ok_photos,
        Property.listing_url.is_not(None),
        Property.country_code.in_(sorted(COUNTRY_CODES)),
        Property.price_usd >= ELIGIBLE_USD_MIN,
        Property.price_usd <= ELIGIBLE_USD_MAX,
        Property.price_date >= _years_ago(today, max_age_years),
        Property.setting.in_(decode_settings(setting_filter)),
        ~blocked,
        ~open_price_report(),
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
            Property.id,
            Property.country_code,
            Property.city,
            Property.setting,
            Property.price_usd,
            Property.source_id,
            Property.images_checked_at,
        ).where(*clauses)
    ).all()
    return [Candidate(*r) for r in rows]


def eligible_counts(db: Session, *, today: date, max_age_years: int) -> dict[str, dict[str, int]]:
    """{country_code: {"urban": n, "rural": n}} for all playable properties."""
    rows = db.execute(
        select(Property.country_code, Property.setting, func.count())
        .where(*eligibility_clauses(today, max_age_years, encode_settings(ALL_SETTINGS)))
        .group_by(Property.country_code, Property.setting)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for cc, setting, n in rows:
        out.setdefault(cc, dict.fromkeys(ALL_SETTINGS, 0))[setting] = n
    return out


def price_quintiles(cands: list[Candidate]) -> dict[str, int]:
    """Map candidate id -> log-price quintile (0..4) within the given pool."""
    ordered = sorted(cands, key=lambda c: math.log(c.price_usd))
    n = len(ordered)
    return {c.id: min(4, i * 5 // n) for i, c in enumerate(ordered)} if n else {}


def recently_verified(cands: list[Candidate], now: datetime, hours: int = 48) -> list[Candidate]:
    """Daily Challenge preference: photos verified in the last 48 hours (Section 5.4)."""
    cutoff = now - timedelta(hours=hours)
    return [c for c in cands if c.images_checked_at and c.images_checked_at >= cutoff]


@dataclass(frozen=True)
class _Rules:
    unique_city: bool = True
    country_cap: bool = True
    source_cap: bool = True
    quintile_spread: bool = True
    setting_mix: bool = True


# Progressive relaxation when the pool can't satisfy every rule.
_RELAXATION = (
    _Rules(),
    _Rules(setting_mix=False),
    _Rules(setting_mix=False, quintile_spread=False),
    _Rules(setting_mix=False, quintile_spread=False, source_cap=False),
    _Rules(setting_mix=False, quintile_spread=False, source_cap=False, unique_city=False),
    _Rules(False, False, False, False, False),
)


def pick_rounds(
    cands: list[Candidate],
    *,
    rng: random.Random,
    where_scope: str = "world",
    setting_filter: str = DEFAULT_SETTING_FILTER,
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
    selected = decode_settings(setting_filter)
    # The per-source cap only makes sense when enough sources exist to satisfy it.
    sources_ok = len({c.source_id for c in cands}) * MAX_PER_SOURCE >= n

    for rules in _RELAXATION:
        caps = _Caps(
            city=rules.unique_city and not (where_scope == "country" and cities_in_pool < n),
            country=rules.country_cap and world,
            source=rules.source_cap and sources_ok,
        )
        need_quint = rules.quintile_spread and pool_quintiles >= MIN_QUINTILES
        need_mix = (
            rules.setting_mix
            and len(selected) > 1
            and all(settings_avail[x] >= MIN_EACH_SETTING for x in selected)
        )
        for _ in range(ATTEMPTS_PER_LEVEL):
            picks = _attempt(cands, by_country, weighted, rng, n, use_country_weighting, caps)
            if picks is None:
                continue
            if need_quint and len({quint[p.id] for p in picks}) < MIN_QUINTILES:
                continue
            if need_mix:
                s = Counter(p.setting for p in picks)
                if any(s[x] < MIN_EACH_SETTING for x in selected):
                    continue
            rng.shuffle(picks)
            return picks

    raise PoolTooSmall("could not build a game from the pool")  # pragma: no cover


@dataclass(frozen=True)
class _Caps:
    city: bool
    country: bool
    source: bool


def _attempt(
    cands: list[Candidate],
    by_country: dict[str, list[Candidate]],
    weighted: list[str],
    rng: random.Random,
    n: int,
    use_country_weighting: bool,
    caps: _Caps,
) -> list[Candidate] | None:
    """One randomized attempt at filling `n` slots under the hard per-slot rules."""
    picks: list[Candidate] = []
    used_ids: set[str] = set()
    used_cities: set[tuple[str, str]] = set()
    per_country: Counter[str] = Counter()
    per_source: Counter[int] = Counter()

    def ok(c: Candidate) -> bool:
        if c.id in used_ids:
            return False
        if caps.city and (c.country_code, c.city) in used_cities:
            return False
        if caps.source and per_source[c.source_id] >= MAX_PER_SOURCE:
            return False
        return not (caps.country and per_country[c.country_code] >= MAX_PER_COUNTRY)

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
        per_source[c.source_id] += 1
    return picks
