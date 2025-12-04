"""Scheduled trend analysis workflows.

This module keeps the orchestration layer for running timeframe-based
trend calculations separate from the core trend logic.
"""

from __future__ import annotations

from configuration import ANALYSIS_PARAMS, FOREX_PAIRS, TIMEFRAMES
from constants import DATA_ERROR_MSG
from externals import db
from externals.data_fetcher import fetch_data
import utils.display as display
from trend.structure import analyze_snake_trend, get_swing_points


def analyze_trend_by_timeframe(timeframe: str) -> None:
    """Run trend analysis for all configured symbols for a given timeframe."""

    display.print_status(f"\n--- 🔄 Running scheduled job for {timeframe} ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Updating {symbol} for {timeframe}...")

        try:
            trend, struct_high, struct_low = analyze_symbol_by_timeframe(
                symbol, timeframe
            )
            high_price = struct_high[1] if struct_high else None
            low_price = struct_low[1] if struct_low else None
            db.update_trend_data(
                symbol,
                timeframe,
                trend,
                float(high_price) if high_price is not None else None,
                float(low_price) if low_price is not None else None,
            )

        except Exception as exc:  # pragma: no cover - defensive logging
            display.print_error(f"Failed to analyze {symbol}/{timeframe}: {exc}")

    display.print_status(f"--- ✅ Scheduled job for {timeframe} complete ---")


def analyze_symbol_by_timeframe(symbol: str, timeframe: str):
    """Analyze a specific symbol/timeframe pair and return trend details."""

    if timeframe not in TIMEFRAMES or timeframe not in ANALYSIS_PARAMS:
        display.print_error(f"Unknown timeframe {timeframe} in analysis.")
        return DATA_ERROR_MSG, None, None

    if symbol not in FOREX_PAIRS:
        display.print_error(f"Unknown symbol {symbol} in analysis.")
        return DATA_ERROR_MSG, None, None

    formatted_timeframe = TIMEFRAMES[timeframe]
    analysis_params = ANALYSIS_PARAMS[timeframe]

    symbol_data_by_timeframe = fetch_data(
        symbol, formatted_timeframe, analysis_params["lookback"]
    )

    if symbol_data_by_timeframe is None:
        return DATA_ERROR_MSG, None, None

    prices = symbol_data_by_timeframe["close"].values
    if len(prices) == 0:
        display.print_status(
            f"  -> {DATA_ERROR_MSG} for {symbol} on TF {timeframe} (No prices returned)"
        )
        return DATA_ERROR_MSG, None, None

    swings = get_swing_points(
        prices, analysis_params["distance"], analysis_params["prominence"]
    )
    return analyze_snake_trend(swings)
