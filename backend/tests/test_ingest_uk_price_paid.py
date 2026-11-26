import random
from dataclasses import asdict
from datetime import date

from ingest.sources.base import PluginContext
from ingest.sources.uk_price_paid import UkPricePaid, keep_row, parse_rows, sample_by_region
from tests.conftest import FIXTURES
from tests.ingest_fakes import FakeGeocoder

CSV = FIXTURES / "uk_price_paid_sample.csv"
SETTINGS = {
    "local_path": str(CSV),
    "filters": {"min_year": 2022, "property_types": ["D", "S", "T", "F"]},
    "max_records_per_run": 100,
    "seed": 1,
}


def run_plugin():
    geo = FakeGeocoder()
    plugin = UkPricePaid(PluginContext(geocoder=geo))
    refs = list(plugin.discover(None, SETTINGS))
    listings = {r: plugin.fetch_and_parse(None, r) for r in refs}
    return refs, listings, geo


def test_filters_rows():
    refs, _, _ = run_plugin()
    ids = {r[-2:] for r in refs}
    # 05 = type O, 06 = category B, 07 = 2019, 08 = record deleted
    assert ids == {"01", "02", "03", "04", "09", "10", "11"}


def test_maps_fields():
    _, listings, _ = run_plugin()
    m = listings["1A000000-0000-0000-0000-000000000001"]
    assert m.price_local == 425_000 and m.currency == "GBP"
    assert m.price_type == "sale_record"
    assert m.price_date == date(2024, 3, 15)
    assert m.country_code == "GB"
    assert m.city == "Manchester" and m.region == "Greater Manchester"
    assert m.property_type == "house"  # S = semi-detached
    assert m.location_precision == "exact"
    assert m.listing_url == (
        "https://landregistry.data.gov.uk/data/ppi/transaction/"
        "1A000000-0000-0000-0000-000000000001/current"
    )
    assert listings["1A000000-0000-0000-0000-000000000002"].property_type == "apartment"
    assert listings["1A000000-0000-0000-0000-000000000004"].property_type == "townhouse"
    assert listings["1A000000-0000-0000-0000-000000000009"].city == "Newcastle upon Tyne"


def test_precision_from_geocoder():
    _, listings, _ = run_plugin()
    assert listings["1A000000-0000-0000-0000-000000000003"].location_precision == "street"
    assert listings["1A000000-0000-0000-0000-000000000004"].location_precision == "district"
    assert listings["1A000000-0000-0000-0000-000000000010"] is None  # no postcode, no match


def test_full_address_geocoded_but_never_returned():
    _, listings, geo = run_plugin()
    assert ("40 SAMPLE STREET", "LONDON", "ZZ2 2BB", "GB") in geo.queries
    for listing in listings.values():
        if listing:
            values = " ".join(str(v) for v in asdict(listing).values()).upper()
            assert "SAMPLE STREET" not in values and "EXAMPLE ROAD" not in values
            assert "ZZ" not in values  # no postcode either


def test_keep_row_rules():
    rows = list(parse_rows(CSV.read_text().splitlines()))
    kept = [r for r in rows if keep_row(r, min_year=2024, property_types={"F"})]
    assert [r["transaction_id"][-3:-1] for r in kept] == ["02"]


def test_sample_spreads_across_regions():
    rows = [{"county": c, "i": i} for c in ("A", "B", "C") for i in range(50)]
    rows += [{"county": "BIG", "i": i} for i in range(1000)]
    sample = sample_by_region(rows, 40, random.Random(0))
    counts = {c: sum(r["county"] == c for r in sample) for c in ("A", "B", "C", "BIG")}
    assert sum(counts.values()) == 40
    assert all(v == 10 for v in counts.values())
