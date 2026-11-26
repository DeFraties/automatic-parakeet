"""Range checks and required-field validation (Section 8.5)."""

import math
from datetime import date

from app.core.config import ELIGIBLE_USD_MAX, ELIGIBLE_USD_MIN
from ingest.models import PRECISIONS, PRICE_TYPES, PROPERTY_TYPES, NormalizedListing

AREA_MIN_M2 = 10
AREA_MAX_M2 = 50_000
PPM2_MIN_USD = 50
PPM2_MAX_USD = 100_000


def validate(listing: NormalizedListing, price_usd: float, today: date | None = None) -> list[str]:
    """Return a list of rejection reasons (empty = valid)."""
    today = today or date.today()
    reasons: list[str] = []
    if not listing.source_ref:
        reasons.append("missing_source_ref")
    if not listing.city or not listing.city.strip():
        reasons.append("missing_city")
    if listing.price_type not in PRICE_TYPES:
        reasons.append("bad_price_type")
    if listing.location_precision not in PRECISIONS:
        reasons.append("bad_location_precision")
    if listing.property_type not in PROPERTY_TYPES:
        reasons.append("bad_property_type")
    if not (isinstance(listing.currency, str) and len(listing.currency) == 3):
        reasons.append("bad_currency")
    if not (
        isinstance(listing.lat, int | float)
        and isinstance(listing.lng, int | float)
        and math.isfinite(listing.lat)
        and math.isfinite(listing.lng)
        and -90 <= listing.lat <= 90
        and -180 <= listing.lng <= 180
    ):
        reasons.append("bad_coordinates")
    if not isinstance(listing.price_local, int) or listing.price_local <= 0:
        reasons.append("bad_price")
    if listing.price_date > today:
        reasons.append("future_date")
    if not (ELIGIBLE_USD_MIN <= price_usd <= ELIGIBLE_USD_MAX):
        reasons.append("price_out_of_range")
    if listing.area_m2 is not None:
        if not (AREA_MIN_M2 <= listing.area_m2 <= AREA_MAX_M2):
            reasons.append("area_out_of_range")
        elif not (PPM2_MIN_USD <= price_usd / listing.area_m2 <= PPM2_MAX_USD):
            reasons.append("price_per_m2_out_of_range")
    if listing.bedrooms is not None and not (0 <= listing.bedrooms <= 50):
        reasons.append("bad_bedrooms")
    if listing.bathrooms is not None and not (0 <= listing.bathrooms <= 50):
        reasons.append("bad_bathrooms")
    if listing.year_built is not None and not (1000 <= listing.year_built <= today.year + 2):
        reasons.append("bad_year_built")
    return reasons
