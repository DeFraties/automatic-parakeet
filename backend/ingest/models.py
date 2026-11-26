"""The ONLY shape a source plugin may return (Section 5.1 / 8.3).

There are deliberately no fields for images, descriptions, agent/owner details or street
addresses, and `slots=True` means a plugin can't attach extra attributes either — so that kind of
data can't be stored by accident.
"""

from dataclasses import dataclass, fields
from datetime import date
from typing import Literal

PriceType = Literal["sale_record", "asking"]
Precision = Literal["exact", "street", "district"]
PropertyType = Literal["house", "apartment", "townhouse", "land", "other"]

PRICE_TYPES = ("sale_record", "asking")
PRECISIONS = ("exact", "street", "district")
PROPERTY_TYPES = ("house", "apartment", "townhouse", "land", "other")


@dataclass(slots=True)
class NormalizedListing:
    source_ref: str
    price_type: PriceType
    price_local: int
    currency: str  # ISO 4217
    price_date: date
    country_code: str  # ISO 3166-1 alpha-2
    city: str
    lat: float
    lng: float
    location_precision: Precision
    property_type: PropertyType
    region: str | None = None
    listing_url: str | None = None
    area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    year_built: int | None = None


LISTING_FIELDS = tuple(f.name for f in fields(NormalizedListing))
