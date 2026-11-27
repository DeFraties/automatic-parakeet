"""Shared fakes for ingestion tests."""

from datetime import date


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


class EverythingUrban:
    """Classifier stub: urban when coordinates exist, unknown otherwise."""

    available = True

    def classify(self, lat, lng, property_type=None, area_m2=None):
        return ("unknown", None) if lat is None else ("urban", 30)


class FakeImageCheck:
    """Photo URL checker stub: URLs containing 'broken' fail; records every call."""

    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return "broken" not in url
