"""Shared trend helpers used across the project.

These functions wrap database access to provide a single place to derive
timeframe-aligned trend bias for a symbol.
"""

from typing import Dict, Mapping, Optional, Sequence

from constants import TREND_BEARISH, TREND_BULLISH, TREND_NEUTRAL
from models import TrendDirection
from trend.trend_repository import fetch_trend_bias, fetch_trend_levels as _fetch_trend_levels


def _normalize_trend_direction(value: Optional[str | TrendDirection]) -> Optional[TrendDirection]:
    if value is None:
        return None

    normalized = TrendDirection.from_raw(value)
    if normalized in {TREND_BULLISH, TREND_BEARISH, TREND_NEUTRAL}:
        return normalized

    return None


def get_trend_by_timeframe(symbol: str, timeframe: str) -> Optional[TrendDirection]:
    """Wrapper around the DB trend provider for testability."""

    result = fetch_trend_bias(symbol, timeframe)
    return _normalize_trend_direction(result)


def get_overall_trend(timeframes: Sequence[str], symbol: str) -> Optional[TrendDirection]:
    """Return the middle/consensus trend when higher timeframes align."""

    trend_values = [
        {
            "trend": get_trend_by_timeframe(symbol, tf),
            "timeframe": tf,
        }
        for tf in timeframes
    ]

    if not trend_values or any(tv["trend"] is None for tv in trend_values):
        return None

    if len(trend_values) >= 3:
        if (
            trend_values[0]["trend"] == trend_values[1]["trend"]
            or trend_values[1]["trend"] == trend_values[2]["trend"]
        ):
            return trend_values[1]["trend"]
        return None

    if len(trend_values) >= 2 and trend_values[0]["trend"] == trend_values[1]["trend"]:
        return trend_values[0]["trend"]

    return None


def get_overall_trend_from_values(
    trend_values: Mapping[str, Optional[TrendDirection]],
    timeframes: Sequence[str] = ("4H", "1D", "1W"),
) -> Optional[TrendDirection]:
    """Return the middle/consensus trend from pre-computed trend values.
    
    This is a pure function that doesn't access the database, suitable for
    replay mode where trends are computed from candles.
    
    Args:
        trend_values: Dict mapping timeframe -> TrendDirection (e.g., {"4H": BULLISH, "1D": BULLISH, "1W": BULLISH})
        timeframes: Ordered sequence of timeframes to check alignment
        
    Returns:
        The consensus trend direction, or None if not aligned.
    """
    # Build ordered list of trends
    trends = [
        {
            "trend": trend_values.get(tf),
            "timeframe": tf,
        }
        for tf in timeframes
    ]

    if not trends or any(tv["trend"] is None for tv in trends):
        return None

    if len(trends) >= 3:
        if (
            trends[0]["trend"] == trends[1]["trend"]
            or trends[1]["trend"] == trends[2]["trend"]
        ):
            return trends[1]["trend"]
        return None

    if len(trends) >= 2 and trends[0]["trend"] == trends[1]["trend"]:
        return trends[0]["trend"]

    return None


def calculate_trend_alignment_strength(
    trend_values: Mapping[str, Optional[TrendDirection]],
    direction: TrendDirection,
) -> int:
    """Count how many timeframes align with the given direction.
    
    This is a pure function - same logic as entry.detector._calculate_trend_alignment_strength
    but reusable without depending on that module.
    """
    count = 0
    for tf_trend in trend_values.values():
        if tf_trend == direction:
            count += 1
    return count


def get_trend_levels(symbol: str, timeframe: str) -> Optional[Dict[str, float]]:
    """Get the high/low trend levels for a symbol/timeframe.
    
    Args:
        symbol: Trading symbol
        timeframe: Timeframe label (e.g., '1D', '1W', '4H')
        
    Returns:
        Dict with 'high' and 'low' keys, or None if not found
    """
    high, low = _fetch_trend_levels(symbol, timeframe)
    if high is None and low is None:
        return None
    return {"high": high, "low": low}
