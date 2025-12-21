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
from utils.logger import get_logger

logger = get_logger(__name__)
from externals.data_fetcher import fetch_data
from trend.workflow import analyze_trend_by_timeframe


def _fetch_closed_candles(timeframe: str, *, lookback: int) -> Mapping[str, pd.DataFrame]:
    """Fetch closed candles for all symbols for the given timeframe."""

    broker_timeframe = TIMEFRAMES.get(timeframe)
    if broker_timeframe is None:
        raise KeyError(f"Unknown timeframe {timeframe!r} requested for candle fetch.")

    candles: dict[str, pd.DataFrame] = {}
    for symbol in FOREX_PAIRS:
        logger.info(
            f"  -> Fetching {lookback} closed candles for {symbol} on {timeframe}..."
        )
        data = fetch_data(
            symbol,
            broker_timeframe,
            lookback,
            timeframe_label=timeframe,
        )
        if data is None:
            logger.error(
                f"No candle data returned for {symbol} on timeframe {timeframe}."
            )
            continue
        if data.empty:
            logger.error(
                f"No closed candles available for {symbol} on timeframe {timeframe}."
            )
            continue
        candles[symbol] = data
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

    logger.info(f"--- 🔄 Running {timeframe} timeframe job ---")
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
    logger.info(f"--- ✅ {timeframe} timeframe job complete ---")

