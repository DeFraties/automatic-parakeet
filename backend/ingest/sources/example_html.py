"""Reference plugin: parses the fixture site in backend/tests/fixtures/example_site/.

It is NOT a real source. Copy it as a starting point for a new plugin and follow
docs/SOURCES.md. It shows the expected shape:

- discover() fetches an index page through the PoliteClient and yields listing URLs
- fetch_and_parse() extracts FACTS ONLY. The fixture page also has photos, a description and an
  agent's phone number; the plugin ignores them (and NormalizedListing has nowhere to put them).
"""

import logging
from collections.abc import Iterable
from datetime import date
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ingest.models import NormalizedListing
from ingest.normalize import normalize_property_type as norm_type
from ingest.normalize import parse_area, parse_price
from ingest.sources.base import SourcePlugin

log = logging.getLogger(__name__)


def _text(tree: HTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    return node.text(strip=True) if node else None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


class ExampleHtml(SourcePlugin):
    key = "example_html"
    display_name = "Example listing site (fixture)"
    homepage = "http://127.0.0.1:8099/"
    price_type = "asking"
    country_codes = ["PT", "HR"]
    license_note = None

    def discover(self, client, settings: dict) -> Iterable[str]:
        base = settings.get("base_url", self.homepage)
        index = client.get(urljoin(base, settings.get("index_path", "index.html")))
        tree = HTMLParser(index.text)
        for a in tree.css("a.listing-link"):
            href = a.attributes.get("href")
            if href:
                yield urljoin(index.url, href)

    def fetch_and_parse(self, client, ref: str) -> NormalizedListing | None:
        page = client.get(ref)
        if page.status != 200:
            return None
        tree = HTMLParser(page.text)
        card = tree.css_first("article.listing")
        if card is None:
            return None
        a = card.attributes
        price = parse_price(_text(card, ".price") or "")
        loc = card.css_first(".locality")
        listed = card.css_first("time.listed")
        listed_on = date.fromisoformat(listed.attributes["datetime"]) if listed else date.today()
        if not price or loc is None or not a.get("data-lat") or not a.get("data-lng"):
            return None
        area = parse_area(_text(card, ".area") or "")
        return NormalizedListing(
            source_ref=a.get("data-listing-id") or ref,
            listing_url=ref,
            price_type="asking",
            price_local=price[0],
            currency=price[1],
            price_date=listed_on,
            country_code=(loc.attributes.get("data-country") or "").upper(),
            city=loc.attributes.get("data-city") or "",
            region=loc.attributes.get("data-region"),
            lat=float(a["data-lat"]),
            lng=float(a["data-lng"]),
            location_precision=a.get("data-precision") or "street",
            property_type=norm_type(_text(card, ".type")),
            area_m2=area,
            bedrooms=_int(_text(card, ".beds")),
            bathrooms=_int(_text(card, ".baths")),
            year_built=_int(_text(card, ".year")),
        )
