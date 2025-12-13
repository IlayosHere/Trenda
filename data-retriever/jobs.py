from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _fetch_symbol_data(
    symbol: str, broker_timeframe: str, lookback: int, timeframe: str
) -> tuple[str, pd.DataFrame | None]:
    """Fetch candle data for a single symbol. Returns (symbol, data) tuple."""
    display.print_status(
        f"  -> Fetching {lookback} closed candles for {symbol} on {timeframe}..."
    )
    data = fetch_data(
        symbol,
        broker_timeframe,
        lookback,
        timeframe_label=timeframe,
    )
    if data is None:
        display.print_error(
            f"  ❌ No candle data returned for {symbol} on timeframe {timeframe}."
        )
        return symbol, None
    if data.empty:
        display.print_error(
            f"  ❌ No closed candles available for {symbol} on timeframe {timeframe}."
        )
        return symbol, None
    return symbol, data


def _fetch_closed_candles(timeframe: str, *, lookback: int) -> Mapping[str, pd.DataFrame]:
    """Fetch closed candles for all symbols for the given timeframe."""

    broker_timeframe = TIMEFRAMES.get(timeframe)
    if broker_timeframe is None:
        raise KeyError(f"Unknown timeframe {timeframe!r} requested for candle fetch.")

    candles: dict[str, pd.DataFrame] = {}

    with ThreadPoolExecutor(max_workers=len(FOREX_PAIRS)) as executor:
        futures = {
            executor.submit(
                _fetch_symbol_data, symbol, broker_timeframe, lookback, timeframe
            ): symbol
            for symbol in FOREX_PAIRS
        }

        for future in as_completed(futures):
            try:
                symbol, data = future.result()
                if data is not None:
                    candles[symbol] = data
            except Exception as exc:
                failed_symbol = futures.get(future, "Unknown Symbol")
                display.print_error(f"  ❌ Critical error fetching {failed_symbol}: {exc}")

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

