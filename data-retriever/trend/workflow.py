"""Scheduled trend analysis workflows.

This module keeps the orchestration layer for running timeframe-based
trend calculations separate from the core trend logic.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from configuration import FOREX_PAIRS, require_analysis_params
from constants import DATA_ERROR_MSG
from trend.trend_repository import update_trend_data
from utils.logger import get_logger

logger = get_logger(__name__)
from trend.structure import TrendAnalysisResult, analyze_snake_trend, get_swing_points


def analyze_single_symbol_trend(
    symbol: str, timeframe: str, data: pd.DataFrame | None
) -> None:
    """Run trend analysis for a single symbol/timeframe pair."""
    logger.info(f"  -> Analyzing trend for {symbol} ({timeframe})...")

    try:
        result = analyze_symbol_by_timeframe(symbol, timeframe, data)
        if result.trend is None:
            logger.info(
                f"  -> Skipping {symbol}: unable to determine trend for {timeframe}."
            )
            return

        high_price = (
            result.structural_high.price if result.structural_high else None
        )
        low_price = result.structural_low.price if result.structural_low else None
        update_trend_data(
            symbol,
            timeframe,
            result.trend,
            float(high_price) if high_price is not None else None,
            float(low_price) if low_price is not None else None,
        )
        logger.info(f"--- ✅ Scheduled job for {timeframe} complete ---")


    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error(f"Failed to analyze {symbol}/{timeframe}: {exc}")



def analyze_symbol_by_timeframe(
    symbol: str, timeframe: str, symbol_data_by_timeframe: pd.DataFrame | None
) -> TrendAnalysisResult:
    """Analyze a specific symbol/timeframe pair and return trend details."""

    if symbol_data_by_timeframe is None:
        logger.info(
            f"  -> {DATA_ERROR_MSG} for {symbol} on TF {timeframe} (No candles provided)"
        )
        return TrendAnalysisResult(None, None, None)

    if symbol not in FOREX_PAIRS:
        logger.error(f"Unknown symbol {symbol} in analysis.")
        return TrendAnalysisResult(None, None, None)

    analysis_params = require_analysis_params(timeframe)

    prices = symbol_data_by_timeframe["close"].values
    if len(prices) == 0:
        logger.info(
            f"  -> {DATA_ERROR_MSG} for {symbol} on TF {timeframe} (No prices returned)"
        )
        return TrendAnalysisResult(None, None, None)

    swings = get_swing_points(
        prices, analysis_params.distance, analysis_params.prominence
    )
    return analyze_snake_trend(swings)
