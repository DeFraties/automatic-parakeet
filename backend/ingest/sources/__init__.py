"""Registry of source plugins. Add new plugins here (see docs/SOURCES.md)."""

from ingest.sources.base import SourcePlugin
from ingest.sources.example_html import ExampleHtml

PLUGINS: dict[str, type[SourcePlugin]] = {p.key: p for p in (ExampleHtml,)}
