"""SourcePlugin interface (Section 8.3). See docs/SOURCES.md before writing a new plugin."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ingest.models import NormalizedListing

if TYPE_CHECKING:
    from ingest.http import PoliteClient


@dataclass
class PluginContext:
    """Services the pipeline hands to a plugin. Plugins must do all HTTP via `client`.
    There is deliberately no geocoder: coordinates come only from the listing (Section 12.8)."""

    cache_dir: str = "./data/cache"
    extra: dict = field(default_factory=dict)


class SourcePlugin(ABC):
    key: str  # "example_html"
    display_name: str  # "HM Land Registry Price Paid Data"
    homepage: str
    price_type: Literal["sale_record", "asking"]
    country_codes: list[str]
    image_hosts: list[str] = []  # hosts photo URLs may come from (Section 7.3)
    # Shown on the About page. Required for open-data licences (Compliance rule 7).
    license_note: str | None = None

    def __init__(self, context: PluginContext | None = None):
        self.ctx = context or PluginContext()

    @abstractmethod
    def discover(self, client: "PoliteClient", settings: dict) -> Iterable[str]:
        """Yield listing URLs or record IDs to fetch."""

    @abstractmethod
    def fetch_and_parse(self, client: "PoliteClient", ref: str) -> NormalizedListing | None:
        """Return a normalized listing (facts + photo URLs + the listing's own coordinates), or
        None to skip (no single numeric price, delisted, not parseable)."""

    def refresh_ref(self, listing_url: str, source_ref: str) -> str:
        """The ref to pass to fetch_and_parse when re-checking a known listing (Section 8.7)."""
        return listing_url
