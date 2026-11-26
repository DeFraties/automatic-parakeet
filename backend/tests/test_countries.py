import re

from app.core.countries import COUNTRIES, REGIONS, REGIONS_BY_KEY, countries_in_region

EXPECTED = {
    "US",
    "CA",
    "MX",
    "BR",
    "PT",
    "ES",
    "GB",
    "FR",
    "IT",
    "PL",
    "HR",
    "ZA",
    "AU",
    "NZ",
    "JP",
    "TW",
}


def _flag_for(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def test_exactly_the_launch_countries():
    assert {c.code for c in COUNTRIES} == EXPECTED
    assert len(COUNTRIES) == 16


def test_every_country_is_well_formed():
    for c in COUNTRIES:
        assert re.fullmatch(r"[A-Z]{2}", c.code)
        assert re.fullmatch(r"[A-Z]{3}", c.currency)
        assert c.region in REGIONS_BY_KEY
        assert c.flag == _flag_for(c.code)
        assert c.name and c.currency_name and c.locale


def test_currencies():
    by = {c.code: c.currency for c in COUNTRIES}
    assert by["HR"] == "EUR"
    assert by["TW"] == "TWD"
    assert by["JP"] == "JPY"
    assert by["GB"] == "GBP"


def test_every_region_has_countries():
    for r in REGIONS:
        assert countries_in_region(r.key)
    assert [c.code for c in countries_in_region("east_asia")] == ["JP", "TW"]
