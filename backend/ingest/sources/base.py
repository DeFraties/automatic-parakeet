"""SourcePlugin interface (Section 8.3). See docs/SOURCES.md before writing a new plugin."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ingest.models import NormalizedListing

if TYPE_CHECKING:
    from ingest.geocode import Geocoder
    from ingest.http import PoliteClient


@dataclass
class PluginContext:
    """Services the pipeline hands to a plugin. Plugins must do all HTTP via `client`."""

    geocoder: "Geocoder | None" = None
    cache_dir: str = "./data/cache"
    extra: dict = field(default_factory=dict)


class SourcePlugin(ABC):
    key: str  # "uk_price_paid"
    display_name: str  # "HM Land Registry Price Paid Data"
    homepage: str
    price_type: Literal["sale_record", "asking"]
    country_codes: list[str]
    # Shown on the About page. Required for open-data licences (Compliance rule 7).
    license_note: str | None = None

    def __init__(self, context: PluginContext | None = None):
        self.ctx = context or PluginContext()

    @abstractmethod
    def discover(self, client: "PoliteClient", settings: dict) -> Iterable[str]:
        """Yield listing URLs or record IDs to fetch."""

    @abstractmethod
    def fetch_and_parse(self, client: "PoliteClient", ref: str) -> NormalizedListing | None:
        """Return a normalized record with FACT FIELDS ONLY, or None to skip."""
