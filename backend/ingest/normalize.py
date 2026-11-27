"""Parsing helpers for messy source data: prices, areas, property types, place names."""

import re

FT2_TO_M2 = 0.09290304
HRK_PER_EUR = 7.53450  # fixed conversion rate when Croatia adopted the euro (1 Jan 2023)

# Longest markers first so "R$" wins over "R", "NT$" over "$", etc.
_CURRENCY_MARKERS: tuple[tuple[str, str], ...] = (
    ("NT$", "TWD"),
    ("AU$", "AUD"),
    ("CA$", "CAD"),
    ("MX$", "MXN"),
    ("NZ$", "NZD"),
    ("US$", "USD"),
    ("R$", "BRL"),
    ("A$", "AUD"),
    ("C$", "CAD"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("¥", "JPY"),
    ("円", "JPY"),
    ("zł", "PLN"),
    ("zl", "PLN"),
    ("kn", "HRK"),
)
_ISO_CODES = {
    "USD", "CAD", "MXN", "BRL", "EUR", "GBP", "PLN", "HRK", "ZAR", "AUD", "NZD", "JPY", "TWD",
}  # fmt: skip

_MULTIPLIERS = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "mio": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "万": 1e4,
    "萬": 1e4,
    "億": 1e8,
    "亿": 1e8,
}

_NUM_RE = re.compile(r"\d[\d\s.,'  ]*")


def parse_number(raw: str, *, prefer_grouping: bool = True) -> float | None:
    """Parse a localized number: "340.000", "425,000", "3 950 000", "1.050.000,50", "1,5", "1.2".

    With one separator occurring once, it's a grouping separator when followed by exactly three
    digits and `prefer_grouping` is true; otherwise it's a decimal separator.
    """
    s = re.sub(r"[\s'  ]", "", raw).strip(".,")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        grp = "," if dec == "." else "."
        s = s.replace(grp, "").replace(dec, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = s.split(sep)
        if len(parts) > 2:
            if not all(len(p) == 3 for p in parts[1:]):
                return None
            s = "".join(parts)
        elif prefer_grouping and len(parts[1]) == 3:
            s = "".join(parts)
        else:
            s = parts[0] + "." + parts[1]
    try:
        return float(s)
    except ValueError:  # pragma: no cover
        return None


def detect_currency(text: str, default: str | None = None) -> str | None:
    iso = re.search(r"\b([A-Z]{3})\b", text)
    if iso and iso.group(1) in _ISO_CODES:
        return iso.group(1)
    for marker, code in _CURRENCY_MARKERS:
        if marker in text:
            return code
    if re.search(r"(^|\s)R\s?\d", text):  # South African rand: "R 3 950 000", "R3,950,000"
        return "ZAR"
    if "$" in text:
        return default or "USD"
    return default


_RANGE_SEP = re.compile(
    r"^\s*(?:thousand|millions?|billion|mio|mn|bn|[kmb万萬億亿])?\s*"
    r"(?:-|–|—|~|to|bis|a|à|até)\s*\D{0,4}$",
    re.IGNORECASE,
)
_MULT_RE = re.compile(r"(thousand|millions?|billion|mio|mn|bn|[kmb万萬億亿])(?![a-z])")


def _amount(m: re.Match, text: str) -> float | None:
    """Value of the number matched by `m`, applying a following multiplier word if any."""
    after = text[m.end() :].strip().lower()
    word = _MULT_RE.match(after)
    mult = _MULTIPLIERS[word.group(1)] if word else 1.0
    # Western suffixes ("1.2m") usually carry decimals; CJK units ("3,800万") usually don't.
    value = parse_number(m.group(0), prefer_grouping=mult in (1.0, 1e4, 1e8))
    return value * mult if value and value > 0 else None


def parse_price(
    text: str, default_currency: str | None = None, *, allow_range_midpoint: bool = False
) -> tuple[int, str] | None:
    """Parse a price string into (whole units, ISO currency), or None to skip the listing.

    "€ 340.000" -> (340000, "EUR"); "$1.2M" -> (1200000, "USD"); "3,800万円" -> (38000000, "JPY");
    "1,280萬" with default TWD -> (12800000, "TWD"). "Price on request" -> None. Ranges such as
    "€300,000 - €350,000" -> None, or the midpoint when `allow_range_midpoint` is set.
    """
    if not text:
        return None
    currency = detect_currency(text, default_currency)
    nums = list(_NUM_RE.finditer(text))
    if not nums or not currency:
        return None  # "Price on request", "POA", "Auction"...
    if len(nums) >= 2 and _RANGE_SEP.match(text[nums[0].end() : nums[1].start()]):
        if not allow_range_midpoint:
            return None
        lo, hi = _amount(nums[0], text[: nums[1].start()]), _amount(nums[1], text)
        return (int(round((lo + hi) / 2)), currency) if lo and hi else None
    value = _amount(nums[0], text)
    return (int(round(value)), currency) if value else None


_AREA_UNITS = (
    (r"(ft²|ft2|sq\.?\s*ft|sqft|square\s+f(ee|oo)t)", FT2_TO_M2),
    (r"(m²|m2|sq\.?\s*m|sqm|㎡|square\s+met(re|er)s?|平米|평)", 1.0),
)


def parse_area(text: str, default_unit: str = "m2") -> float | None:
    """ "120 m²" -> 120.0; "1,292 sq ft" -> 120.03; "85sqm" -> 85.0 (always returns m²)."""
    if not text:
        return None
    m = _NUM_RE.search(text)
    if not m:
        return None
    value = parse_number(m.group(0))
    if value is None or value <= 0:
        return None
    rest = text[m.end() :].lower()
    for pattern, factor in _AREA_UNITS:
        if re.match(r"\s*" + pattern, rest):
            return round(value * factor, 1)
    return round(value * (FT2_TO_M2 if default_unit == "ft2" else 1.0), 1)


_TYPE_WORDS: tuple[tuple[str, str], ...] = (
    (r"town\s*-?house|terrace|terraced|row\s*house|maisonette|duplex", "townhouse"),
    (r"apartment|apartamento|appartement|appartamento|flat|condo|condominium|studio|penthouse"
     r"|mieszkanie|stan|piso|マンション|公寓|unit", "apartment"),
    (r"house|detached|semi|bungalow|villa|cottage|casa|maison|dom|chalet|farmhouse|一戸建て"
     r"|透天", "house"),
    (r"land|plot|lot|terreno|terrain|działka|zemljište", "land"),
)  # fmt: skip


def normalize_property_type(text: str | None) -> str:
    """Map free-text property types to house | apartment | townhouse | land | other."""
    if not text:
        return "other"
    low = text.lower()
    for pattern, value in _TYPE_WORDS:
        if re.search(pattern, low):
            return value
    return "other"


_SMALL_WORDS = {"upon", "on", "the", "in", "by", "le", "la", "de", "and", "under", "with", "of"}


def title_place(name: str | None) -> str | None:
    """ "NEWCASTLE UPON TYNE" -> "Newcastle upon Tyne"; "STOKE-ON-TRENT" -> "Stoke-on-Trent"."""
    if not name:
        return None
    out = []
    for i, word in enumerate(re.split(r"(\s+|-)", name.strip().lower())):
        if i > 0 and word in _SMALL_WORDS:
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return "".join(out)


def convert_legacy_currency(price: int, currency: str) -> tuple[int, str]:
    """Croatian kuna -> euro at the fixed rate; everything else unchanged."""
    if currency == "HRK":
        return int(round(price / HRK_PER_EUR)), "EUR"
    return price, currency
