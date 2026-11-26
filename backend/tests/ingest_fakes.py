"""Shared fakes for ingestion tests."""

from datetime import date

from ingest.geocode import GeoResult


class FakeGeocoder:
    """Precision by postcode prefix; records every (street, city, postcode) it was asked about."""

    BY_POSTCODE = {
        "ZZ1": GeoResult(53.4300, -2.2300, "exact"),
        "ZZ2": GeoResult(51.5450, -0.0550, "exact"),
        "ZZ3": GeoResult(50.1240, -5.6800, "street"),
        "ZZ4": GeoResult(53.8300, -1.5800, "district"),
        "ZZ9": GeoResult(54.9780, -1.6170, "exact"),
    }

    def __init__(self):
        self.queries = []

    def geocode_address(self, *, street, city, postcode, country_code):
        self.queries.append((street, city, postcode, country_code))
        if not postcode:
            return None
        return self.BY_POSTCODE.get(postcode[:3])


class FakeFx:
    RATES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067}

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.calls = []

    def rate_to_usd(self, currency, on: date):
        self.calls.append((currency, on))
        if currency in self.missing:
            return None
        return self.RATES.get(currency)


class NoRaster:
    available = False

    def classify(self, lat, lng, property_type=None, area_m2=None):
        return "unknown", None
