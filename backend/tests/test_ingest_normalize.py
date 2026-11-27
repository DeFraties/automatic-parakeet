from datetime import date

import pytest

from ingest.models import IMAGE_FIELDS, LISTING_FIELDS, NormalizedImage, NormalizedListing
from ingest.normalize import (
    convert_legacy_currency,
    normalize_property_type,
    parse_area,
    parse_number,
    parse_price,
    title_place,
)
from ingest.validate import validate


@pytest.mark.parametrize(
    "text,expected",
    [
        ("€ 340.000", (340_000, "EUR")),
        ("$1.2M", (1_200_000, "USD")),
        ("£425,000", (425_000, "GBP")),
        ("¥38,000,000", (38_000_000, "JPY")),
        ("3,800万円", (38_000_000, "JPY")),
        ("R$ 1.050.000", (1_050_000, "BRL")),
        ("R 3 950 000", (3_950_000, "ZAR")),
        ("R3,950,000", (3_950_000, "ZAR")),
        ("890 000 zł", (890_000, "PLN")),
        ("NT$32,000,000", (32_000_000, "TWD")),
        ("A$2.15m", (2_150_000, "AUD")),
        ("CA$865,000", (865_000, "CAD")),
        ("MX$7,800,000", (7_800_000, "MXN")),
        ("NZ$ 720 000", (720_000, "NZD")),
        ("EUR 1.250.000,00", (1_250_000, "EUR")),
        ("kn 1.507.000", (1_507_000, "HRK")),
        ("1,5 mio €", (1_500_000, "EUR")),
        ("€1.5 million", (1_500_000, "EUR")),
        ("450k USD", (450_000, "USD")),
        ("Price: 299.950 €", (299_950, "EUR")),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_parse_price_default_currency_for_bare_dollar():
    assert parse_price("$865,000", default_currency="CAD") == (865_000, "CAD")
    assert parse_price("425000", default_currency="GBP") == (425_000, "GBP")


@pytest.mark.parametrize("text", ["", "Price on request", "€", "POA", "€ 0"])
def test_parse_price_rejects(text):
    assert parse_price(text) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("340.000", 340000),
        ("1,5", 1.5),
        ("1.050.000,50", 1050000.5),
        ("3 950 000", 3950000),
        ("1,234.5", 1234.5),
        ("12.5", 12.5),
        ("1.2.3", None),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("120 m²", 120.0),
        ("120m2", 120.0),
        ("85 sqm", 85.0),
        ("85 sq m", 85.0),
        ("1,292 sq ft", 120.0),
        ("1292 ft²", 120.0),
        ("1,615 sqft", 150.0),
        ("2,000 square feet", 185.8),
        ("95,5 m²", 95.5),
        ("70㎡", 70.0),
    ],
)
def test_parse_area(text, expected):
    assert parse_area(text) == pytest.approx(expected, abs=0.1)


def test_parse_area_default_unit():
    assert parse_area("1000", default_unit="ft2") == pytest.approx(92.9, abs=0.1)
    assert parse_area("n/a") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Apartamento", "apartment"),
        ("Flat", "apartment"),
        ("Condo", "apartment"),
        ("Detached house", "house"),
        ("Semi-detached", "house"),
        ("Villa", "house"),
        ("Terraced house", "townhouse"),
        ("Townhouse", "townhouse"),
        ("Building plot", "land"),
        ("Kuća (house)", "house"),
        ("Parking space", "other"),
        (None, "other"),
    ],
)
def test_property_types(text, expected):
    assert normalize_property_type(text) == expected


def test_title_place():
    assert title_place("NEWCASTLE UPON TYNE") == "Newcastle upon Tyne"
    assert title_place("STOKE-ON-TRENT") == "Stoke-on-Trent"
    assert title_place("GREATER MANCHESTER") == "Greater Manchester"


def test_hrk_converts_at_fixed_rate():
    assert convert_legacy_currency(1_507_000, "HRK") == (200_013, "EUR")
    assert convert_legacy_currency(7_534_500, "HRK") == (1_000_000, "EUR")
    assert convert_legacy_currency(100, "EUR") == (100, "EUR")


def test_listing_schema_has_no_room_for_pii_or_image_bytes():
    """Section 13.1: fails if someone adds a description, contact or image-bytes field."""
    forbidden = {"description", "agent", "phone", "email", "address", "street", "owner",
                 "contact", "photographer", "image_data", "image_bytes", "bytes", "blob",
                 "content", "thumbnail"}  # fmt: skip
    assert not forbidden & set(LISTING_FIELDS)
    assert not forbidden & set(IMAGE_FIELDS)
    assert set(IMAGE_FIELDS) == {"url", "width", "height", "kind"}
    listing = _listing()
    with pytest.raises(AttributeError):
        listing.description = "lovely"  # slots: can't attach extra data
    with pytest.raises(AttributeError):
        listing.images[0].data = b"..."


HOST = "images.example.test"


def _listing(**kw):
    base = dict(source_ref="r1", listing_url="https://listings.test/r1", price_type="asking",
                price_local=300_000, currency="EUR", price_date=date(2025, 1, 1),
                country_code="PT", city="Lisbon", lat=38.7, lng=-9.1,
                location_precision="exact", property_type="apartment", area_m2=85.0,
                images=[NormalizedImage(f"https://{HOST}/{i}.jpg") for i in range(3)])  # fmt: skip
    base.update(kw)
    return NormalizedListing(**base)


def _validate(listing, usd):
    return validate(listing, usd, image_hosts=[HOST], today=date(2026, 1, 1))


def test_validation_accepts_good_record():
    assert _validate(_listing(), 324_000) == []
    assert _validate(_listing(lat=None, lng=None, location_precision=None), 324_000) == []


@pytest.mark.parametrize(
    "kw,usd,reason",
    [
        ({}, 4_999, "price_out_of_range"),
        ({}, 100_000_001, "price_out_of_range"),
        ({"area_m2": 9}, 300_000, "area_out_of_range"),
        ({"area_m2": 50_001}, 3_000_000, "area_out_of_range"),
        ({"area_m2": 1000}, 40_000, "price_per_m2_out_of_range"),  # $40/m²
        ({"area_m2": 20}, 2_500_000, "price_per_m2_out_of_range"),  # $125k/m²
        ({"area_m2": 100}, 8_000, "looks_like_rent"),  # $80/m²: probably monthly rent
        ({"is_rental": True}, 300_000, "rental"),
        ({"lat": 123}, 300_000, "bad_coordinates"),
        ({"lng": None}, 300_000, "bad_coordinates"),
        ({"city": " "}, 300_000, "missing_city"),
        ({"listing_url": ""}, 300_000, "missing_listing_url"),
        ({"price_type": "rent"}, 300_000, "bad_price_type"),
        ({"location_precision": "street"}, 300_000, "bad_location_precision"),
        ({"property_type": "castle"}, 300_000, "bad_property_type"),
        ({"price_date": date(2027, 1, 1)}, 300_000, "future_date"),
        ({"bedrooms": 99}, 300_000, "bad_bedrooms"),
        ({"year_built": 3000}, 300_000, "bad_year_built"),
        ({"images": [NormalizedImage(f"https://{HOST}/1.jpg")]}, 300_000, "too_few_photos"),
        ({"images": [NormalizedImage("https://other.test/1.jpg"),
                     NormalizedImage(f"https://{HOST}/2.jpg")]}, 300_000,
         "image_host_not_allowed"),
    ],
)  # fmt: skip
def test_validation_rejects_outliers(kw, usd, reason):
    assert reason in _validate(_listing(**kw), usd)


@pytest.mark.parametrize(
    "text,default,expected",
    [
        ("1,280萬", "TWD", (12_800_000, "TWD")),
        ("NT$1,280萬", None, (12_800_000, "TWD")),
        ("3,800万円", None, (38_000_000, "JPY")),
        ("1億2000万円", None, None),  # compound units: skipped rather than misread
    ],
)
def test_cjk_units(text, default, expected):
    got = parse_price(text, default)
    if expected is None:
        assert got != (120_000_000, "JPY") or got is None
    else:
        assert got == expected


@pytest.mark.parametrize(
    "text", ["€300,000 - €350,000", "£1.2m to £1.4m", "R$ 900.000 – R$ 950.000", "€1.5m - €2m"]
)
def test_price_ranges_skipped_by_default(text):
    assert parse_price(text) is None


def test_price_range_midpoint_when_allowed():
    assert parse_price("€300,000 - €350,000", allow_range_midpoint=True) == (325_000, "EUR")
    assert parse_price("€1.5m - €2m", allow_range_midpoint=True) == (1_750_000, "EUR")


@pytest.mark.parametrize("text", ["Price on request", "POA", "Auction", "By negotiation", ""])
def test_no_single_price_is_skipped(text):
    assert parse_price(text) is None
