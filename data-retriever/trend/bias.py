"""Shared trend helpers used across the project.

These functions wrap database access to provide a single place to derive
timeframe-aligned trend bias for a symbol.
"""

from typing import Optional, Sequence

from constants import TREND_BEARISH, TREND_BULLISH, TREND_NEUTRAL, TrendBias
from trend.trend_repository import fetch_trend_bias


def _normalize_trend_bias(value: Optional[str]) -> Optional[TrendBias]:
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    normalized = value.lower()
    if normalized == TREND_BULLISH:
        return TREND_BULLISH
    if normalized == TREND_BEARISH:
        return TREND_BEARISH
    if normalized == TREND_NEUTRAL:
        return TREND_NEUTRAL

    return None


def get_trend_by_timeframe(symbol: str, timeframe: str) -> Optional[TrendBias]:
    """Wrapper around the DB trend provider for testability."""

    result = fetch_trend_bias(symbol, timeframe)
    return _normalize_trend_bias(result)


def get_overall_trend(timeframes: Sequence[str], symbol: str) -> Optional[TrendBias]:
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
