"""The ONLY shapes a source plugin may return (Section 5.1 / 8.3).

There are deliberately no fields for descriptions, agent/owner/photographer details, street
addresses or image bytes, and `slots=True` means a plugin can't attach extra attributes either,
so that kind of data can't be stored by accident. Photos are URLs on the source, nothing more.
"""

from dataclasses import dataclass, field, fields
from datetime import date
from typing import Literal

PriceType = Literal["asking", "sale_record"]
Precision = Literal["exact", "approximate"]
PropertyType = Literal["house", "apartment", "townhouse", "land", "other"]

PRICE_TYPES = ("asking", "sale_record")
PRECISIONS = ("exact", "approximate")
PROPERTY_TYPES = ("house", "apartment", "townhouse", "land", "other")
IMAGE_KINDS = ("photo", "floorplan")


@dataclass(slots=True)
class NormalizedImage:
    url: str  # absolute https URL of the image as published by the source
    width: int | None = None
    height: int | None = None
    kind: str | None = None  # photo | floorplan | None


@dataclass(slots=True)
class NormalizedListing:
    source_ref: str
    listing_url: str
    price_type: PriceType
    price_local: int
    currency: str  # ISO 4217
    price_date: date  # sold date if the listing shows one, otherwise the day it was scraped
    country_code: str  # ISO 3166-1 alpha-2
    city: str
    property_type: PropertyType
    images: list[NormalizedImage] = field(default_factory=list)  # in the listing's order
    region: str | None = None
    # Only coordinates the listing itself provides (embedded JSON, map widget). Never geocoded.
    lat: float | None = None
    lng: float | None = None
    location_precision: Precision | None = None
    area_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    year_built: int | None = None
    is_rental: bool = False  # plugin's flag for monthly rents; these are rejected


LISTING_FIELDS = tuple(f.name for f in fields(NormalizedListing))
IMAGE_FIELDS = tuple(f.name for f in fields(NormalizedImage))
