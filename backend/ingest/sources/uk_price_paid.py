"""HM Land Registry Price Paid Data importer (England & Wales, open data). Section 8.4.

Contains HM Land Registry data © Crown copyright and database right. This data is licensed
under the Open Government Licence v3.0.

The CSV has addresses but no coordinates. Each address is geocoded IN MEMORY (Nominatim, then the
postcode centroid from postcodes.io); only lat/lng, city and region are kept. The street address
is never returned to the pipeline, so it can't be stored.
"""

import csv
import logging
import random
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from ingest.models import NormalizedListing
from ingest.normalize import title_place
from ingest.sources.base import SourcePlugin

log = logging.getLogger(__name__)

# CSV columns (the files have no header row)
COLUMNS = (
    "transaction_id", "price", "date", "postcode", "property_type", "old_new", "duration",
    "paon", "saon", "street", "locality", "town", "district", "county", "ppd_category",
    "record_status",
)  # fmt: skip

TYPE_MAP = {"D": "house", "S": "house", "T": "townhouse", "F": "apartment"}  # "O" (other) skipped

TRANSACTION_URL = "https://landregistry.data.gov.uk/data/ppi/transaction/{id}/current"


def parse_rows(lines: Iterable[str]) -> Iterator[dict]:
    for row in csv.reader(lines):
        if len(row) >= len(COLUMNS):
            yield dict(zip(COLUMNS, (c.strip() for c in row), strict=False))


def keep_row(row: dict, *, min_year: int, property_types: set[str]) -> bool:
    if row["ppd_category"] != "A":  # B = non-standard (repossessions, buy-to-let, …)
        return False
    if row.get("record_status", "A") not in ("A", "C"):  # D = deleted
        return False
    if row["property_type"] not in property_types or row["property_type"] not in TYPE_MAP:
        return False
    try:
        return int(row["date"][:4]) >= min_year and int(row["price"]) > 0
    except ValueError:
        return False


def sample_by_region(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Random sample of up to n rows, spread round-robin across counties."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["county"], []).append(r)
    for g in groups.values():
        rng.shuffle(g)
    keys = sorted(groups)
    rng.shuffle(keys)
    out: list[dict] = []
    while len(out) < n and keys:
        for k in list(keys):
            if not groups[k]:
                keys.remove(k)
                continue
            out.append(groups[k].pop())
            if len(out) >= n:
                break
    return out


class UkPricePaid(SourcePlugin):
    key = "uk_price_paid"
    display_name = "HM Land Registry Price Paid Data"
    homepage = "https://www.gov.uk/government/collections/price-paid-data"
    price_type = "sale_record"
    country_codes = ["GB"]
    license_note = (
        "Contains HM Land Registry data © Crown copyright and database right {year}. "
        "This data is licensed under the Open Government Licence v3.0."
    )

    def __init__(self, context=None):
        super().__init__(context)
        self._rows: dict[str, dict] = {}

    def _files(self, client, settings: dict) -> list[Path]:
        if settings.get("local_path"):
            return [Path(settings["local_path"])]
        files = []
        cache_dir = Path(self.ctx.cache_dir) / self.key
        for url in settings.get("urls", []):
            name = Path(urlsplit(url).path).name or "price_paid.csv"
            files.append(client.download(url, cache_dir / name, max_age_hours=24 * 7))
        return files

    def discover(self, client, settings: dict) -> Iterable[str]:
        filters = settings.get("filters", {}) or {}
        min_year = int(filters.get("min_year", date.today().year - 3))
        types = set(filters.get("property_types", list(TYPE_MAP)))
        n = int(settings.get("max_records_per_run", settings.get("sample_size", 2000)))
        rng = random.Random(settings.get("seed"))

        kept: list[dict] = []
        for path in self._files(client, settings):
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                kept.extend(
                    r
                    for r in parse_rows(fh)
                    if keep_row(r, min_year=min_year, property_types=types)
                )
        sample = sample_by_region(kept, n, rng)
        log.info("[%s] %d eligible rows, sampled %d", self.key, len(kept), len(sample))
        self._rows = {r["transaction_id"].strip("{}"): r for r in sample}
        yield from list(self._rows)

    def fetch_and_parse(self, client, ref: str) -> NormalizedListing | None:
        row = self._rows.pop(ref, None)
        if row is None or self.ctx.geocoder is None:
            return None
        # Geocode the full address in memory; it is discarded after this call.
        street = " ".join(p for p in (row["paon"], row["street"]) if p)
        geo = self.ctx.geocoder.geocode_address(
            street=street,
            city=row["town"],
            postcode=row["postcode"] or None,
            country_code="GB",
        )
        if geo is None:
            return None
        return NormalizedListing(
            source_ref=ref,
            listing_url=TRANSACTION_URL.format(id=ref),
            price_type="sale_record",
            price_local=int(row["price"]),
            currency="GBP",
            price_date=datetime.strptime(row["date"][:10], "%Y-%m-%d").date(),
            country_code="GB",
            region=title_place(row["county"]),
            city=title_place(row["town"]) or title_place(row["district"]) or "",
            lat=geo.lat,
            lng=geo.lng,
            location_precision=geo.precision,
            property_type=TYPE_MAP[row["property_type"]],
        )
