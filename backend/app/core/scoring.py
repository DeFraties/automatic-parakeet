"""Scoring (Section 3) and money helpers (slider bounds, nice rounding)."""

import math

from app.core.config import MAX_POINTS, USD_SLIDER_MAX, USD_SLIDER_MIN, ZERO_POINT_RATIO


def score_guess(guess: float, actual: float) -> int:
    """Log-ratio score. Both values MUST be in the same currency."""
    if not (guess > 0 and actual > 0) or not math.isfinite(guess) or not math.isfinite(actual):
        raise ValueError("guess and actual must be positive finite numbers")
    error = abs(math.log(guess / actual))
    return round(MAX_POINTS * max(0.0, 1 - error / math.log(ZERO_POINT_RATIO)))


def pct_off(guess: float, actual: float) -> float:
    """Absolute percentage difference of guess vs actual (same currency)."""
    return abs(guess - actual) / actual * 100


def reveal_label(pct: float) -> str:
    if pct <= 5:
        return "Bullseye!"
    if pct <= 15:
        return "In the ballpark"
    if pct <= 35:
        return "Close-ish"
    if pct <= 100:
        return "Way off"
    return "Different planet"


def usd_to_local(amount_usd: float, rate_to_usd: float) -> float:
    """`rate_to_usd` is USD per 1 unit of local currency (price_usd = price_local * rate)."""
    return amount_usd / rate_to_usd


def local_to_usd(amount_local: float, rate_to_usd: float) -> float:
    return amount_local * rate_to_usd


_NICE_STEPS = (1, 2, 5)


def nice_floor(x: float) -> int:
    """Largest value of the form {1,2,5} x 10^n that is <= x."""
    if x <= 0:
        raise ValueError("x must be positive")
    exp = math.floor(math.log10(x))
    best = 10**exp
    for step in _NICE_STEPS:
        candidate = step * 10**exp
        if candidate <= x * (1 + 1e-9):
            best = candidate
    return int(best) if best >= 1 else 1


def nice_ceil(x: float) -> int:
    """Smallest value of the form {1,2,5} x 10^n that is >= x."""
    if x <= 0:
        raise ValueError("x must be positive")
    exp = math.floor(math.log10(x))
    for step in (*_NICE_STEPS, 10):
        candidate = step * 10**exp
        if candidate >= x * (1 - 1e-9):
            return int(max(1, candidate))
    return int(10 ** (exp + 1))  # pragma: no cover


def slider_bounds(currency: str, rate_to_usd: float | None) -> tuple[int, int]:
    """Slider bounds in the guess currency. USD: fixed range. Local: converted + nice-rounded
    outward (min rounded down, max rounded up) so the full USD range is always covered."""
    if currency == "USD" or rate_to_usd is None:
        return USD_SLIDER_MIN, USD_SLIDER_MAX
    return (
        nice_floor(usd_to_local(USD_SLIDER_MIN, rate_to_usd)),
        nice_ceil(usd_to_local(USD_SLIDER_MAX, rate_to_usd)),
    )


def fx_hint(currency: str, rate_to_usd: float) -> str | None:
    """Human-readable "1 USD ≈ X CUR" hint. None for USD properties."""
    if currency == "USD":
        return None
    per_usd = 1 / rate_to_usd
    if per_usd >= 100:
        shown = f"{per_usd:,.0f}"
    elif per_usd >= 10:
        shown = f"{per_usd:,.1f}"
    else:
        shown = f"{per_usd:,.2f}"
    return f"1 USD ≈ {shown} {currency}"
