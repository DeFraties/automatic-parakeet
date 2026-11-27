from datetime import date

import pytest

from ingest.models import LISTING_FIELDS, NormalizedListing
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


def test_listing_schema_has_no_room_for_pii():
    assert "image_url" in LISTING_FIELDS  # a photo URL only (hotlinked), never image data
    forbidden = {
        "image",
        "images",
        "photo",
        "photos",
        "description",
        "agent",
        "phone",
        "email",
        "address",
        "street",
        "owner",
        "contact",
    }
    assert not forbidden & set(LISTING_FIELDS)
    listing = _listing()
    with pytest.raises(AttributeError):
        listing.photos = ["x.jpg"]  # slots: can't attach extra data


def _listing(**kw):
    base = dict(
        source_ref="r1",
        price_type="asking",
        price_local=300_000,
        currency="EUR",
        price_date=date(2025, 1, 1),
        country_code="PT",
        city="Lisbon",
        lat=38.7,
        lng=-9.1,
        location_precision="exact",
        property_type="apartment",
        area_m2=85.0,
    )
    base.update(kw)
    return NormalizedListing(**base)


def test_validation_accepts_good_record():
    assert validate(_listing(), 324_000, today=date(2026, 1, 1)) == []


@pytest.mark.parametrize(
    "kw,usd,reason",
    [
        ({}, 4_999, "price_out_of_range"),
        ({}, 100_000_001, "price_out_of_range"),
        ({"area_m2": 9}, 300_000, "area_out_of_range"),
        ({"area_m2": 50_001}, 3_000_000, "area_out_of_range"),
        ({"area_m2": 1000}, 40_000, "price_per_m2_out_of_range"),  # $40/m²
        ({"area_m2": 20}, 2_500_000, "price_per_m2_out_of_range"),  # $125k/m²
        ({"lat": 123}, 300_000, "bad_coordinates"),
        ({"city": " "}, 300_000, "missing_city"),
        ({"price_type": "rent"}, 300_000, "bad_price_type"),
        ({"location_precision": "city"}, 300_000, "bad_location_precision"),
        ({"property_type": "castle"}, 300_000, "bad_property_type"),
        ({"price_date": date(2027, 1, 1)}, 300_000, "future_date"),
        ({"bedrooms": 99}, 300_000, "bad_bedrooms"),
        ({"year_built": 3000}, 300_000, "bad_year_built"),
    ],
)
def test_validation_rejects_outliers(kw, usd, reason):
    assert reason in validate(_listing(**kw), usd, today=date(2026, 1, 1))


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://cdn.example.com/p/1.jpg", "https://cdn.example.com/p/1.jpg"),
        ("http://cdn.example.com/1.jpg", "http://cdn.example.com/1.jpg"),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,AAAA", None),
        ("/relative/1.jpg", None),
        ("https://x.com/" + "a" * 1000, None),
        (None, None),
    ],
)
def test_clean_image_url(url, expected):
    from ingest.pipeline import clean_image_url

    assert clean_image_url(url) == expected
