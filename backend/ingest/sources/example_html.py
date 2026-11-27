"""Reference plugin (Section 8.4): parses the FICTIONAL fixture site in backend/tests/fixtures/.

It is not a real source. Copy it as the starting point for a new plugin and follow
docs/SOURCES.md. It shows every pattern a real plugin needs:

- discover(): read a search-results page through the PoliteClient and yield listing URLs
- fetch_and_parse(): prefer the site's embedded JSON, fall back to HTML selectors
- normalize the price (skip "price on request" and ranges) and the area (m²/ft²)
- take coordinates ONLY from the listing itself (JSON or the site's map widget)
- collect photo URLs in the listing's order, choosing the largest size the site already
  publishes that is <= 1600 px, and label floor plans
- ignore everything else on the page: descriptions, agent names/phones/emails, addresses
"""

import json
import logging
import re
from collections.abc import Iterable
from datetime import date
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ingest.models import NormalizedImage, NormalizedListing
from ingest.normalize import normalize_property_type, parse_area, parse_price
from ingest.sources.base import SourcePlugin

log = logging.getLogger(__name__)

MAX_IMAGE_WIDTH = 1600


def _text(node, selector: str) -> str | None:
    found = node.css_first(selector)
    return found.text(strip=True) if found else None


def _int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _is_floorplan(label: str | None) -> bool:
    return bool(label) and bool(re.search(r"floor\s*plan|planta|grundriss", label, re.I))


class ExampleHtml(SourcePlugin):
    key = "example_html"
    display_name = "Example Listings (fixture)"
    homepage = "http://127.0.0.1:8099/"
    price_type = "asking"
    country_codes = ["PT", "HR"]
    image_hosts = ["images.example.test"]
    license_note = None

    def discover(self, client, settings: dict) -> Iterable[str]:
        self.allow_midpoint = bool(settings.get("allow_price_range_midpoint", False))
        base = settings.get("base_url", self.homepage)
        page = client.get(urljoin(base, settings.get("search_path", "example_search.html")))
        tree = HTMLParser(page.text)
        for a in tree.css("a.result-link"):
            href = a.attributes.get("href")
            if href:
                yield urljoin(page.url, href)

    # -- parsing ----------------------------------------------------------------------------
    def _price(self, text: str) -> tuple[int, str] | None:
        return parse_price(text, allow_range_midpoint=getattr(self, "allow_midpoint", False))

    def fetch_and_parse(self, client, ref: str) -> NormalizedListing | None:
        page = client.get(ref)
        if page.status != 200:
            return None
        tree = HTMLParser(page.text)
        blob = tree.css_first("script#listing-data")
        if blob is not None:
            try:
                return self._from_json(json.loads(blob.text()), ref)
            except (ValueError, KeyError, TypeError) as e:
                log.info("embedded JSON unusable on %s (%s); falling back to HTML", ref, e)
        return self._from_html(tree, ref)

    def _from_json(self, d: dict, ref: str) -> NormalizedListing | None:
        if d.get("status") == "for_rent":
            return None
        price = d.get("price") or {}
        if price.get("amount"):
            parsed = (int(price["amount"]), price["currency"])
        else:
            parsed = self._price(price.get("display", ""))
        if not parsed:
            return None  # no single numeric price
        addr, geo = d.get("address") or {}, d.get("geo") or {}
        images = [
            NormalizedImage(
                url=p["url"],
                width=_int(p.get("width")),
                height=_int(p.get("height")),
                kind="floorplan" if _is_floorplan(p.get("label")) else "photo",
            )
            for p in d.get("photos", [])
            if p.get("url") and (_int(p.get("width")) or 0) <= MAX_IMAGE_WIDTH
        ]
        lat, lng = _float(geo.get("lat")), _float(geo.get("lng"))
        return NormalizedListing(
            source_ref=str(d["id"]),
            listing_url=ref,
            price_type="asking",
            price_local=parsed[0],
            currency=parsed[1],
            price_date=date.today(),  # asking price: the day it was (first) scraped
            country_code=addr.get("country", ""),
            city=addr.get("city", ""),
            region=addr.get("region"),
            lat=lat,
            lng=lng,
            location_precision=("exact" if geo.get("precision") == "exact" else "approximate")
            if lat is not None
            else None,
            property_type=normalize_property_type(d.get("type")),
            area_m2=parse_area(d.get("area", "")),
            bedrooms=_int(d.get("bedrooms")),
            bathrooms=_int(d.get("bathrooms")),
            year_built=_int(d.get("yearBuilt")),
            images=images,
        )  # note: address.street, agent and description are deliberately ignored

    def _from_html(self, tree, ref: str) -> NormalizedListing | None:
        card = tree.css_first("article.listing")
        if card is None:
            return None
        parsed = self._price(_text(card, ".price") or "")
        if not parsed:
            return None  # "Price on request", auctions without a guide price, ranges
        loc = card.css_first(".locality")
        if loc is None:
            return None
        widget = card.css_first(".map")
        lat = _float(widget.attributes.get("data-lat")) if widget else None
        lng = _float(widget.attributes.get("data-lng")) if widget else None
        approx = widget is not None and widget.attributes.get("data-approximate") == "true"
        images = []
        for img in card.css(".gallery img"):
            a = img.attributes
            url = a.get("data-src-large") or a.get("data-src")  # largest published <= 1600 px
            if url:
                kind = "floorplan" if a.get("data-kind") == "floorplan" else "photo"
                images.append(NormalizedImage(url=urljoin(ref, url), kind=kind))
        return NormalizedListing(
            source_ref=card.attributes.get("data-listing-id") or ref,
            listing_url=ref,
            price_type="asking",
            price_local=parsed[0],
            currency=parsed[1],
            price_date=date.today(),
            country_code=loc.attributes.get("data-country") or "",
            city=loc.attributes.get("data-city") or "",
            region=loc.attributes.get("data-region"),
            lat=lat,
            lng=lng,
            location_precision=("approximate" if approx else "exact") if lat is not None else None,
            property_type=normalize_property_type(_text(card, ".type")),
            area_m2=parse_area(_text(card, ".area") or ""),
            bedrooms=_int(_text(card, ".beds")),
            bathrooms=_int(_text(card, ".baths")),
            year_built=_int(_text(card, ".year")),
            images=images,
        )
