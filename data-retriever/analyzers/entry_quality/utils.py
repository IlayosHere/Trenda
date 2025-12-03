from __future__ import annotations

from typing import Iterable


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` between ``low`` and ``high``."""

    return max(low, min(high, value))


def body_size(candle) -> float:
    """Return the absolute body size of a candle."""

    return abs(candle.close - candle.open)


def full_range(candle) -> float:
    """Return the full high-to-low range of a candle."""

    return candle.high - candle.low


def wick_up(candle) -> float:
    """Return the size of the upper wick."""

    return candle.high - max(candle.open, candle.close)


def wick_down(candle) -> float:
    """Return the size of the lower wick."""

    return min(candle.open, candle.close) - candle.low


def wick_in_direction_of_trend(candle, trend: str) -> float:
    """Return the wick that aligns with the given trend direction."""

    return wick_down(candle) if trend == "bullish" else wick_up(candle)


def wick_into_aoi(candle, trend: str, aoi_low: float, aoi_high: float) -> float:
    """Compute how much of the wick (excluding body) overlaps the AOI."""

    if trend == "bullish":
        wick_start, wick_end = candle.low, min(candle.open, candle.close)
    else:
        wick_start, wick_end = max(candle.open, candle.close), candle.high

    overlap_start = max(wick_start, aoi_low)
    overlap_end = min(wick_end, aoi_high)
    overlap = max(0.0, overlap_end - overlap_start)
    return overlap


def penetration_depth(candle, aoi_low: float, aoi_high: float) -> float:
    """Return the AOI penetration depth normalized by the AOI height."""

    aoi_height = aoi_high - aoi_low
    if aoi_height <= 0:
        return 0.0

    overlap_start = max(candle.low, aoi_low)
    overlap_end = min(candle.high, aoi_high)
    overlap = max(0.0, overlap_end - overlap_start)
    return overlap / aoi_height


def candle_direction_with_trend(candle, trend: str) -> bool:
    """Return True if the candle direction aligns with the trend."""
    is_bull_candle = candle.close > candle.open
    return (trend == "bullish") == is_bull_candle
