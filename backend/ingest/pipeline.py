"""fetch -> parse -> normalize -> validate -> dedupe -> upsert (Section 8.1)."""

import logging
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.countries import is_launch_country
from app.models import Blocklist, IngestRun, Property, Source, utcnow
from ingest.config import SourceConfig
from ingest.fx import FxService
from ingest.http import MIN_DELAY_S, PoliteClient, RobotsDisallowed, SourceBlocked
from ingest.models import NormalizedListing
from ingest.normalize import convert_legacy_currency
from ingest.setting import SettingClassifier
from ingest.sources.base import SourcePlugin
from ingest.validate import validate

log = logging.getLogger(__name__)

DUP_DISTANCE_M = 15
DUP_PRICE_RATIO = 0.02
COMMIT_EVERY = 100
MAX_DUP_DETAILS = 50


@dataclass
class IngestDeps:
    client: PoliteClient
    fx: FxService
    classifier: SettingClassifier


def ensure_source(db: Session, plugin: SourcePlugin, cfg: SourceConfig | None) -> Source:
    src = db.execute(select(Source).where(Source.key == plugin.key)).scalar_one_or_none()
    if src is None:
        src = Source(key=plugin.key)
        db.add(src)
    src.display_name = plugin.display_name
    src.homepage = plugin.homepage
    note = plugin.license_note
    src.license_note = note.replace("{year}", str(date.today().year)) if note else None
    src.enabled = bool(cfg and cfg.enabled)
    db.flush()
    return src


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_cross_source_duplicate(db: Session, prop: Property) -> Property | None:
    """Another source's record within 15 m whose USD price is within 2%."""
    dlat = DUP_DISTANCE_M / 111_320
    dlng = dlat / max(0.01, math.cos(math.radians(prop.lat)))
    rows = db.execute(
        select(Property).where(
            Property.source_id != prop.source_id,
            Property.lat.between(prop.lat - dlat, prop.lat + dlat),
            Property.lng.between(prop.lng - dlng, prop.lng + dlng),
            Property.price_usd.between(
                prop.price_usd * (1 - DUP_PRICE_RATIO), prop.price_usd * (1 + DUP_PRICE_RATIO)
            ),
        )
    ).scalars()
    for other in rows:
        if _distance_m(prop.lat, prop.lng, other.lat, other.lng) <= DUP_DISTANCE_M:
            return other
    return None


MAX_IMAGE_URL = 1000


def clean_image_url(url: str | None) -> str | None:
    """Keep only plain absolute http(s) URLs; anything else is dropped (the record is kept)."""
    if not url or len(url) > MAX_IMAGE_URL:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return url.strip()


def _apply(prop: Property, listing: NormalizedListing, *, price_usd: float, rate: float) -> None:
    moved = prop.lat is not None and (prop.lat, prop.lng) != (listing.lat, listing.lng)
    prop.listing_url = listing.listing_url
    prop.image_url = listing.image_url
    prop.price_type = listing.price_type
    prop.price_local = listing.price_local
    prop.currency = listing.currency
    prop.price_usd = round(price_usd, 2)
    prop.fx_rate_to_usd = rate
    prop.price_date = listing.price_date
    prop.country_code = listing.country_code
    prop.region = listing.region
    prop.city = listing.city
    prop.lat, prop.lng = listing.lat, listing.lng
    prop.location_precision = listing.location_precision
    prop.property_type = listing.property_type
    prop.area_m2 = listing.area_m2
    prop.bedrooms = listing.bedrooms
    prop.bathrooms = listing.bathrooms
    prop.year_built = listing.year_built
    if moved or prop.sv_status is None:
        # location changed: street-level images must be re-checked
        prop.sv_status, prop.pano_id = "unchecked", None
        prop.mly_status, prop.mly_image_id = "unchecked", None


def run_source(
    db: Session,
    plugin: SourcePlugin,
    cfg: SourceConfig,
    deps: IngestDeps,
    *,
    limit: int | None = None,
) -> IngestRun:
    src = ensure_source(db, plugin, cfg)
    run = IngestRun(source_key=plugin.key, status="running")
    db.add(run)
    db.commit()

    deps.client.default_delay = max(MIN_DELAY_S, cfg.delay_seconds)

    st = SimpleNamespace(
        discovered=0, fetched=0, inserted=0, updated=0, skipped=0, rejected=0,
        dropped_country=0, possible_duplicates=0,
    )  # fmt: skip
    blocked = set(
        db.execute(select(Blocklist.source_ref).where(Blocklist.source_id == src.id)).scalars()
    )
    reasons: Counter[str] = Counter()
    dropped_countries: Counter[str] = Counter()
    dup_pairs: list[list[str]] = []
    cap = min(limit or cfg.max_records_per_run, cfg.max_records_per_run)
    log.info("[%s] run started (max %d records)", plugin.key, cap)

    try:
        plugin_settings = {**cfg.settings, "max_records_per_run": cap}
        for ref in plugin.discover(deps.client, plugin_settings):
            st.discovered += 1
            if ref in blocked:
                st.skipped += 1
                reasons["blocklisted"] += 1
                continue
            if st.fetched >= cap:
                break
            st.fetched += 1
            try:
                listing = plugin.fetch_and_parse(deps.client, ref)
            except RobotsDisallowed:
                st.skipped += 1
                reasons["robots_disallowed"] += 1
                continue
            except SourceBlocked:
                raise
            except Exception as e:
                log.warning("[%s] failed to parse %s: %s", plugin.key, ref, e)
                st.rejected += 1
                reasons["parse_error"] += 1
                continue
            if listing is None:
                st.skipped += 1
                reasons["plugin_skipped"] += 1
                continue

            listing.country_code = (listing.country_code or "").upper()
            if not is_launch_country(listing.country_code):
                st.dropped_country += 1
                dropped_countries[listing.country_code or "?"] += 1
                continue

            listing.price_local, listing.currency = convert_legacy_currency(
                listing.price_local, listing.currency.upper()
            )
            rate = deps.fx.rate_to_usd(listing.currency, listing.price_date)
            if rate is None:
                log.warning(
                    "[%s] no FX rate for %s on %s — skipping %s",
                    plugin.key, listing.currency, listing.price_date, ref,
                )  # fmt: skip
                st.rejected += 1
                reasons["no_fx_rate"] += 1
                continue
            price_usd = listing.price_local * rate
            # Photos only when the source is configured to allow them (`photos: false` = off).
            listing.image_url = (
                clean_image_url(listing.image_url) if cfg.settings.get("photos", True) else None
            )

            problems = validate(listing, price_usd)
            if problems:
                st.rejected += 1
                reasons.update(problems)
                continue

            prop = db.execute(
                select(Property).where(
                    Property.source_id == src.id, Property.source_ref == listing.source_ref
                )
            ).scalar_one_or_none()
            is_new = prop is None
            if is_new:
                prop = Property(source_id=src.id, source_ref=listing.source_ref, is_active=True)
            _apply(prop, listing, price_usd=price_usd, rate=rate)
            prop.setting, prop.setting_class_raw = deps.classifier.classify(
                listing.lat, listing.lng, listing.property_type, listing.area_m2
            )
            prop.updated_at = utcnow()
            db.add(prop)
            db.flush()
            if is_new:
                st.inserted += 1
            else:
                st.updated += 1

            dup = find_cross_source_duplicate(db, prop)
            if dup is not None:
                st.possible_duplicates += 1
                log.info("[%s] possible duplicate: %s ~ %s", plugin.key, prop.id, dup.id)
                if len(dup_pairs) < MAX_DUP_DETAILS:
                    dup_pairs.append([prop.id, dup.id])

            if (st.inserted + st.updated) % COMMIT_EVERY == 0:
                db.commit()
        run.status = "ok"
    except SourceBlocked as e:
        # Everything saved so far was validated: keep it, stop the run.
        run.status = "blocked"
        run.message = f"BLOCKED: {e}. Stopped; will not retry until the next scheduled run."
        log.error("[%s] %s", plugin.key, run.message)
    except Exception as e:
        db.rollback()
        run = db.merge(run)
        run.status = "error"
        run.message = f"{type(e).__name__}: {e}"
        log.exception("[%s] run failed", plugin.key)

    if dropped_countries:
        log.info("[%s] dropped %d non-launch-country records: %s",
                 plugin.key, st.dropped_country, dict(dropped_countries))  # fmt: skip
    for k, v in vars(st).items():
        setattr(run, k, v)
    run.details = {
        "reasons": dict(reasons),
        "dropped_countries": dict(dropped_countries),
        "possible_duplicates": dup_pairs,
        "http_requests": deps.client.requests_made,
    }
    run.finished_at = utcnow()
    db.commit()
    log.info(
        "[%s] %s: discovered=%d fetched=%d inserted=%d updated=%d skipped=%d rejected=%d "
        "dropped_country=%d possible_duplicates=%d",
        plugin.key, run.status, st.discovered, st.fetched, st.inserted, st.updated,
        st.skipped, st.rejected, st.dropped_country, st.possible_duplicates,
    )  # fmt: skip
    return run
