"""Range checks and required-field validation (Section 8.5)."""

import math
from datetime import date
from urllib.parse import urlsplit

from app.core.config import ELIGIBLE_USD_MAX, ELIGIBLE_USD_MIN, get_settings
from app.core.countries import COUNTRIES_BY_CODE
from ingest.models import PRECISIONS, PRICE_TYPES, PROPERTY_TYPES, NormalizedListing

AREA_MIN_M2 = 10
AREA_MAX_M2 = 50_000
PPM2_MIN_USD = 50
PPM2_MAX_USD = 100_000


def image_host_allowed(url: str, allowed_hosts: list[str]) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in set(allowed_hosts)


def validate(
    listing: NormalizedListing,
    price_usd: float,
    *,
    image_hosts: list[str],
    today: date | None = None,
) -> list[str]:
    """Return a list of rejection reasons (empty = valid)."""
    today = today or date.today()
    reasons: list[str] = []
    if not listing.source_ref:
        reasons.append("missing_source_ref")
    if not listing.listing_url or urlsplit(listing.listing_url).scheme not in ("http", "https"):
        reasons.append("missing_listing_url")
    if not listing.city or not listing.city.strip():
        reasons.append("missing_city")
    if listing.price_type not in PRICE_TYPES:
        reasons.append("bad_price_type")
    if listing.location_precision not in (*PRECISIONS, None):
        reasons.append("bad_location_precision")
    if listing.property_type not in PROPERTY_TYPES:
        reasons.append("bad_property_type")
    if not (isinstance(listing.currency, str) and len(listing.currency) == 3):
        reasons.append("bad_currency")
    has_lat, has_lng = listing.lat is not None, listing.lng is not None
    if has_lat != has_lng or (
        has_lat
        and not (
            math.isfinite(listing.lat)
            and math.isfinite(listing.lng)
            and -90 <= listing.lat <= 90
            and -180 <= listing.lng <= 180
        )
    ):
        reasons.append("bad_coordinates")
    if not isinstance(listing.price_local, int) or listing.price_local <= 0:
        reasons.append("bad_price")
    if listing.price_date > today:
        reasons.append("future_date")
    if listing.is_rental:
        reasons.append("rental")
    if not (ELIGIBLE_USD_MIN <= price_usd <= ELIGIBLE_USD_MAX):
        reasons.append("price_out_of_range")
    if listing.area_m2 is not None:
        if not (AREA_MIN_M2 <= listing.area_m2 <= AREA_MAX_M2):
            reasons.append("area_out_of_range")
        else:
            ppm2 = price_usd / listing.area_m2
            if not (PPM2_MIN_USD <= ppm2 <= PPM2_MAX_USD):
                reasons.append("price_per_m2_out_of_range")
            else:
                country = COUNTRIES_BY_CODE.get(listing.country_code)
                if country and ppm2 < country.min_sale_ppm2_usd:
                    reasons.append("looks_like_rent")
    if len(listing.images) < get_settings().min_ok_photos:
        reasons.append("too_few_photos")
    if any(not image_host_allowed(img.url, image_hosts) for img in listing.images):
        reasons.append("image_host_not_allowed")
    if listing.bedrooms is not None and not (0 <= listing.bedrooms <= 50):
        reasons.append("bad_bedrooms")
    if listing.bathrooms is not None and not (0 <= listing.bathrooms <= 50):
        reasons.append("bad_bathrooms")
    if listing.year_built is not None and not (1000 <= listing.year_built <= today.year + 2):
        reasons.append("bad_year_built")
    return reasons
