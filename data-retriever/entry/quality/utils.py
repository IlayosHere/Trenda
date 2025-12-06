from __future__ import annotations

from models import TrendDirection
from models.market import Candle


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` between ``low`` and ``high``."""

    return max(low, min(high, value))


def body_size(candle: Candle) -> float:
    """Return the absolute body size of a candle."""

    return abs(candle.close - candle.open)


def full_range(candle: Candle) -> float:
    """Return the full high-to-low range of a candle."""

    return candle.high - candle.low


def wick_up(candle: Candle) -> float:
    """Return the size of the upper wick."""

    return candle.high - max(candle.open, candle.close)


def wick_down(candle: Candle) -> float:
    """Return the size of the lower wick."""

    return min(candle.open, candle.close) - candle.low


def wick_in_direction_of_trend(candle: Candle, trend: TrendDirection) -> float:
    """Return the wick that aligns with the given trend direction."""

    return (
        wick_down(candle)
        if trend == TrendDirection.BULLISH
        else wick_up(candle)
    )


def wick_into_aoi(
    candle: Candle, trend: TrendDirection, aoi_low: float, aoi_high: float
) -> float:
    """Compute how much of the wick (excluding body) overlaps the AOI."""

    if trend == TrendDirection.BULLISH:
        wick_start, wick_end = candle.low, min(candle.open, candle.close)
    else:
        wick_start, wick_end = max(candle.open, candle.close), candle.high

    overlap_start = max(wick_start, aoi_low)
    overlap_end = min(wick_end, aoi_high)
    overlap = max(0.0, overlap_end - overlap_start)
    return overlap


def penetration_depth(candle: Candle, aoi_low: float, aoi_high: float) -> float:
    """Return the AOI penetration depth normalized by the AOI height."""

    aoi_height = aoi_high - aoi_low
    if aoi_height <= 0:
        return 0.0

    overlap_start = max(candle.low, aoi_low)
    overlap_end = min(candle.high, aoi_high)
    overlap = max(0.0, overlap_end - overlap_start)
    return overlap / aoi_height


def candle_direction_with_trend(candle: Candle, trend: TrendDirection) -> bool:
    """Return True if the candle direction aligns with the trend."""
    is_bull_candle = candle.close > candle.open
    return (
        (is_bull_candle and trend == TrendDirection.BULLISH)
        or (not is_bull_candle and trend == TrendDirection.BEARISH)
    )
