import math

import pytest

from app.core.config import MAX_POINTS, USD_SLIDER_MAX, USD_SLIDER_MIN
from app.core.scoring import (
    fx_hint,
    nice_ceil,
    nice_floor,
    pct_off,
    reveal_label,
    score_guess,
    slider_bounds,
    usd_to_local,
)


def test_exact_guess_is_max():
    assert score_guess(425_000, 425_000) == MAX_POINTS == 5000


def test_symmetric_in_log_space():
    assert score_guess(200, 100) == score_guess(50, 100)
    assert score_guess(200, 100) == 1845


def test_ten_percent_off():
    assert score_guess(110, 100) == 4566


@pytest.mark.parametrize("ratio", [3, 3.5, 10, 1 / 3, 1 / 10])
def test_three_x_or_more_is_zero(ratio):
    assert score_guess(100 * ratio, 100) == 0


@pytest.mark.parametrize("bad", [0, -5, math.inf, math.nan])
def test_rejects_non_positive(bad):
    with pytest.raises(ValueError):
        score_guess(bad, 100)


def test_currency_conversion_before_scoring():
    # Property: ¥68,000,000 at 0.0067 USD/JPY. Guess $455,600 USD == ¥68,000,000.
    rate = 0.0067
    actual_local = 68_000_000
    usd_guess = actual_local * rate
    assert score_guess(usd_to_local(usd_guess, rate), actual_local) == 5000
    # Comparing USD guess against local price directly would be badly wrong:
    assert score_guess(usd_guess, actual_local) == 0


def test_normal_and_hard_equivalent_guesses_score_the_same():
    rate = 1.08  # EUR
    actual = 510_000
    hard_guess_local = 600_000
    normal_guess_usd = hard_guess_local * rate
    assert score_guess(usd_to_local(normal_guess_usd, rate), actual) == score_guess(
        hard_guess_local, actual
    )


@pytest.mark.parametrize(
    "pct,label",
    [
        (0, "Bullseye!"),
        (5, "Bullseye!"),
        (5.1, "In the ballpark"),
        (15, "In the ballpark"),
        (35, "Close-ish"),
        (100, "Way off"),
        (100.1, "Different planet"),
    ],
)
def test_labels(pct, label):
    assert reveal_label(pct) == label


def test_pct_off():
    assert pct_off(110, 100) == pytest.approx(10)
    assert pct_off(50, 100) == pytest.approx(50)


@pytest.mark.parametrize(
    "x,floor,ceil",
    [(1, 1, 1), (3, 2, 5), (7.5, 5, 10), (750_000, 500_000, 1_000_000), (200, 200, 200)],
)
def test_nice_rounding(x, floor, ceil):
    assert nice_floor(x) == floor
    assert nice_ceil(x) == ceil


def _is_nice(v: int) -> bool:
    s = str(v)
    return s[0] in "125" and set(s[1:]) <= {"0"}


@pytest.mark.parametrize(
    "currency,rate,expected",
    [
        ("JPY", 1 / 150, (500_000, 10_000_000_000)),
        ("TWD", 1 / 32, (100_000, 2_000_000_000)),
        ("ZAR", 1 / 18.5, (50_000, 1_000_000_000)),
        ("PLN", 1 / 4, (20_000, 200_000_000)),
        ("EUR", 1.08, (2_000, 50_000_000)),
    ],
)
def test_hard_slider_bounds_are_nice(currency, rate, expected):
    lo, hi = slider_bounds(currency, rate)
    assert (lo, hi) == expected
    assert _is_nice(lo) and _is_nice(hi)
    # Bounds always cover the whole USD range.
    assert lo <= usd_to_local(USD_SLIDER_MIN, rate)
    assert hi >= usd_to_local(USD_SLIDER_MAX, rate)


def test_usd_slider_bounds():
    assert slider_bounds("USD", None) == (5_000, 50_000_000)


def test_fx_hint():
    assert fx_hint("JPY", 1 / 151) == "1 USD ≈ 151 JPY"
    assert fx_hint("EUR", 1.08) == "1 USD ≈ 0.93 EUR"
    assert fx_hint("USD", 1.0) is None
