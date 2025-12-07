from __future__ import annotations

from datetime import datetime, timezone
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
from utils.candles import last_expected_close_time, trim_to_closed_candles


def _fetch_closed_candles(timeframe: str, *, lookback: int) -> Mapping[str, pd.DataFrame]:
    """Fetch closed candles for all symbols for the given timeframe."""

    mt5_timeframe = TIMEFRAMES.get(timeframe)
    if mt5_timeframe is None:
        raise KeyError(f"Unknown timeframe {timeframe!r} requested for candle fetch.")

    candles: dict[str, pd.DataFrame] = {}
    cutoff_time = last_expected_close_time(timeframe, now=datetime.now(timezone.utc))

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
        trimmed = trim_to_closed_candles(data, timeframe, now=cutoff_time)
        if len(trimmed) < len(data):
            display.print_status(
                f"     ⚠️ Dropped {len(data) - len(trimmed)} non-closed candles for {symbol}."
            )
        if trimmed.empty:
            display.print_error(
                f"  ❌ No closed candles available for {symbol} on timeframe {timeframe}."
            )
            continue
        candles[symbol] = trimmed
    return candles


def _limit_candles(
    candles: Mapping[str, pd.DataFrame], *, count: int | None
) -> Mapping[str, pd.DataFrame]:
    """Return only the latest ``count`` candles for each symbol."""

    if count is None:
        return candles

    return {symbol: df.tail(count) for symbol, df in candles.items()}


def _run_timeframe_analysis(
    timeframe: str,
    *,
    include_aoi: bool,
    trend_candles: Mapping[str, pd.DataFrame],
    aoi_candles: Mapping[str, pd.DataFrame] | None,
) -> None:
    """Run AOI (when requested) and trend analysis for the provided candles."""

    if include_aoi:
        analyze_aoi_by_timeframe(timeframe, aoi_candles or {})

    analyze_trend_by_timeframe(timeframe, trend_candles)


def run_timeframe_job(timeframe: str, *, include_aoi: bool) -> None:
    """Fetch candles once and run analyses for a timeframe."""

    display.print_status(f"\n--- 🔄 Running {timeframe} timeframe job ---")
    analysis_params = require_analysis_params(timeframe)
    trend_lookback = analysis_params.lookback
    aoi_lookback = require_aoi_lookback(timeframe) if include_aoi else None
    fetch_lookback = max(trend_lookback, aoi_lookback or 0)

    candles = _fetch_closed_candles(timeframe, lookback=fetch_lookback)
    trend_candles = _limit_candles(candles, count=trend_lookback)
    aoi_candles = _limit_candles(candles, count=aoi_lookback)

    _run_timeframe_analysis(
        timeframe,
        include_aoi=include_aoi,
        trend_candles=trend_candles,
        aoi_candles=aoi_candles,
    )
    display.print_status(f"--- ✅ {timeframe} timeframe job complete ---\n")

