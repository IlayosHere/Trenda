from __future__ import annotations

from typing import Mapping

import pandas as pd

from aoi import analyze_aoi_by_timeframe
from configuration import (
    FOREX_PAIRS,
    TIMEFRAMES,
    require_analysis_params,
    require_aoi_lookback,
)
import utils.display as display
from externals.data_fetcher import fetch_data
from trend.workflow import analyze_trend_by_timeframe


def _fetch_closed_candles(
    timeframe: str, *, include_aoi_lookback: bool = False
) -> Mapping[str, pd.DataFrame]:
    """Fetch closed candles for all symbols for the given timeframe."""

    mt5_timeframe = TIMEFRAMES.get(timeframe)
    if mt5_timeframe is None:
        raise KeyError(f"Unknown timeframe {timeframe!r} requested for candle fetch.")

    analysis_params = require_analysis_params(timeframe)
    lookback = analysis_params.lookback
    if include_aoi_lookback:
        lookback = max(lookback, require_aoi_lookback(timeframe))

    candles: dict[str, pd.DataFrame] = {}
    for symbol in FOREX_PAIRS:
        display.print_status(
            f"  -> Fetching {lookback} closed candles for {symbol} on {timeframe}..."
        )
        data = fetch_data(symbol, mt5_timeframe, lookback)
        if data is None:
            display.print_error(
                f"  ❌ No candle data returned for {symbol} on timeframe {timeframe}."
            )
            continue
        candles[symbol] = data
    return candles


def _run_timeframe_analysis(
    timeframe: str, *, include_aoi: bool, candles: Mapping[str, pd.DataFrame]
) -> None:
    """Run AOI (when requested) and trend analysis for the provided candles."""

    if include_aoi:
        analyze_aoi_by_timeframe(timeframe, candles)

    analyze_trend_by_timeframe(timeframe, candles)


def run_timeframe_job(timeframe: str, *, include_aoi: bool) -> None:
    """Fetch candles once and run analyses for a timeframe."""

    display.print_status(f"\n--- 🔄 Running {timeframe} timeframe job ---")
    candles = _fetch_closed_candles(timeframe, include_aoi_lookback=include_aoi)
    _run_timeframe_analysis(timeframe, include_aoi=include_aoi, candles=candles)
    display.print_status(f"--- ✅ {timeframe} timeframe job complete ---\n")
