"""Utility helpers for working with forex symbols and pip calculations."""

from typing import Tuple


def get_pip_size(symbol: str) -> float:
    """Return the pip size for a forex symbol.

    Most major forex pairs are quoted with a pip size of 0.0001. JPY pairs are
    quoted with a pip size of 0.01. This helper keeps the logic in one place so
    that conversions between price units and pips stay consistent throughout the
    code base.
    """

    if symbol.upper().endswith("JPY"):
        return 0.01
    return 0.0001


def price_to_pips(price_difference: float, pip_size: float) -> float:
    """Convert a price difference to pips using the provided pip size."""

    return price_difference / pip_size if pip_size else 0.0


def pips_to_price(pips: float, pip_size: float) -> float:
    """Convert a number of pips back into a raw price difference."""

    return pips * pip_size


def normalize_price_range(lower: float, upper: float) -> Tuple[float, float]:
    """Ensure the lower/upper bounds are ordered correctly."""

    if lower <= upper:
        return lower, upper
    return upper, lower

