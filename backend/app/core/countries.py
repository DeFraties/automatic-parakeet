"""The 16 launch countries (Section 1.4 / 5.5).

This is the ONLY place in the codebase that lists countries. Everything else (API, selection,
ingestion whitelist, frontend dropdown via /api/meta) derives from this data.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    emoji: str = "🌍"


@dataclass(frozen=True)
class Country:
    code: str  # ISO 3166-1 alpha-2
    name: str
    flag: str
    currency: str  # ISO 4217
    currency_name: str
    region: str  # Region.key
    locale: str  # default BCP-47 locale
    in_ecb_fx: bool = True  # currency covered by ECB reference rates (Frankfurter)?


REGIONS: tuple[Region, ...] = (
    Region("north_america", "North America", "🌎"),
    Region("south_america", "South America", "🌎"),
    Region("europe", "Europe", "🌍"),
    Region("africa", "Africa", "🌍"),
    Region("oceania", "Oceania", "🌏"),
    Region("east_asia", "East Asia", "🌏"),
)

COUNTRIES: tuple[Country, ...] = (
    Country("US", "United States", "🇺🇸", "USD", "US dollar", "north_america", "en-US"),
    Country("CA", "Canada", "🇨🇦", "CAD", "Canadian dollar", "north_america", "en-CA"),
    Country("MX", "Mexico", "🇲🇽", "MXN", "Mexican peso", "north_america", "es-MX"),
    Country("BR", "Brazil", "🇧🇷", "BRL", "Brazilian real", "south_america", "pt-BR"),
    Country("PT", "Portugal", "🇵🇹", "EUR", "Euro", "europe", "pt-PT"),
    Country("ES", "Spain", "🇪🇸", "EUR", "Euro", "europe", "es-ES"),
    Country("GB", "United Kingdom", "🇬🇧", "GBP", "British pound", "europe", "en-GB"),
    Country("FR", "France", "🇫🇷", "EUR", "Euro", "europe", "fr-FR"),
    Country("IT", "Italy", "🇮🇹", "EUR", "Euro", "europe", "it-IT"),
    Country("PL", "Poland", "🇵🇱", "PLN", "Polish złoty", "europe", "pl-PL"),
    Country("HR", "Croatia", "🇭🇷", "EUR", "Euro", "europe", "hr-HR"),
    Country("ZA", "South Africa", "🇿🇦", "ZAR", "South African rand", "africa", "en-ZA"),
    Country("AU", "Australia", "🇦🇺", "AUD", "Australian dollar", "oceania", "en-AU"),
    Country("NZ", "New Zealand", "🇳🇿", "NZD", "New Zealand dollar", "oceania", "en-NZ"),
    Country("JP", "Japan", "🇯🇵", "JPY", "Japanese yen", "east_asia", "ja-JP"),
    Country("TW", "Taiwan", "🇹🇼", "TWD", "New Taiwan dollar", "east_asia", "zh-TW", False),
)

COUNTRIES_BY_CODE: dict[str, Country] = {c.code: c for c in COUNTRIES}
REGIONS_BY_KEY: dict[str, Region] = {r.key: r for r in REGIONS}
COUNTRY_CODES: frozenset[str] = frozenset(COUNTRIES_BY_CODE)


def get_country(code: str) -> Country | None:
    return COUNTRIES_BY_CODE.get(code.upper()) if code else None


def is_launch_country(code: str | None) -> bool:
    return bool(code) and code.upper() in COUNTRY_CODES


def countries_in_region(region_key: str) -> list[Country]:
    return [c for c in COUNTRIES if c.region == region_key]


def ecb_currencies() -> list[str]:
    """Launch currencies (excluding USD) available from ECB / Frankfurter."""
    return sorted({c.currency for c in COUNTRIES if c.in_ecb_fx and c.currency != "USD"})


def fallback_currencies() -> list[str]:
    """Launch currencies that need the FallbackFxProvider (not covered by the ECB)."""
    return sorted({c.currency for c in COUNTRIES if not c.in_ecb_fx})


def where_flag(where_scope: str, where_value: str | None) -> str:
    """Flag/emoji for a game's "Where" setting (leaderboards)."""
    if where_scope == "country" and where_value in COUNTRIES_BY_CODE:
        return COUNTRIES_BY_CODE[where_value].flag
    if where_scope == "region" and where_value in REGIONS_BY_KEY:
        return REGIONS_BY_KEY[where_value].emoji
    return "🌍"
