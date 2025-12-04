"""Shared trend helpers used across analyzers.

These functions wrap database access to provide a single place to derive
timeframe-aligned trend bias for a symbol.
"""

from typing import Optional, Sequence

from externals import db


def get_trend_by_timeframe(symbol: str, timeframe: str) -> Optional[str]:
    """Wrapper around the DB trend provider for testability."""

    result = db.fetch_trend_bias(symbol, timeframe)
    return result


def get_overall_trend(timeframes: Sequence[str], symbol: str) -> Optional[str]:
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
