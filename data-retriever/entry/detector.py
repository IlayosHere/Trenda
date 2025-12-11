from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from configuration import FOREX_PAIRS, TIMEFRAMES, require_analysis_params
from entry.models import EntryPattern
from entry.pattern_finder import find_entry_pattern
from entry.quality import evaluate_entry_quality
from aoi.aoi_repository import fetch_tradable_aois
from entry.signal_repository import store_entry_signal
from externals.data_fetcher import fetch_data
from models import AOIZone, SignalData, TrendDirection
from models.market import Candle
from trend.bias import get_overall_trend, get_trend_by_timeframe
import utils.display as display


DEFAULT_TREND_ALIGNMENT: tuple[str, ...] = ("4H", "1D", "1W")


def run_1h_entry_scan_job(
    timeframe: str,
    trend_alignment_timeframes: Sequence[str] = DEFAULT_TREND_ALIGNMENT,
) -> None:
    """Scheduled 1H entry scan across all forex pairs and tradable AOIs."""

    mt5_timeframe = TIMEFRAMES.get(timeframe)
    lookback = require_analysis_params(timeframe).lookback

    display.print_status(f"\n--- 🔍 Running {timeframe} entry scan across symbols ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Checking {symbol}...")
        candles = fetch_data(
            symbol,
            mt5_timeframe,
            int(lookback),
            timeframe_label=timeframe,
        )
        if candles is None:
            display.print_error(
                f"  ❌ Skipping {symbol}: no candle data returned for timeframe {timeframe}."
            )
            continue
        if candles.empty:
            display.print_error(
                f"  ❌ Skipping {symbol}: no closed candles available after trimming."
            )
            continue

        trend_snapshot = _collect_trend_snapshot(trend_alignment_timeframes, symbol)
        direction = TrendDirection.from_raw(
            get_overall_trend(trend_alignment_timeframes, symbol)
        )
        if direction is None:
            continue

        aois = fetch_tradable_aois(symbol)
        if not aois:
            continue

        for aoi_data in aois:
            lower = aoi_data.get("lower_bound")
            upper = aoi_data.get("upper_bound")
            aoi = AOIZone(lower=lower, upper=upper)
            signal = scan_1h_for_entry(direction, aoi, candles)
            if signal:
                entry_id = store_entry_signal(
                    symbol=symbol,
                    trend_snapshot=trend_snapshot,
                    aoi_high=aoi.upper,
                    aoi_low=aoi.lower,
                    signal_time=signal.signal_time,
                    candles=signal.candles,
                    trade_quality=signal.trade_quality,
                )
                display.print_status(
                    f"    ✅ Entry signal {entry_id} found for {symbol} at AOI {aoi.lower}-{aoi.upper}."
                )


def _collect_trend_snapshot(
    timeframes: Sequence[str], symbol: str
) -> Mapping[str, Optional[TrendDirection]]:
    return {tf: get_trend_by_timeframe(symbol, tf) for tf in timeframes}

def scan_1h_for_entry(
    direction: TrendDirection,
    aoi: AOIZone,
    candles_1h: Union[pd.DataFrame, Sequence[Union[Candle, Mapping[str, Any]]]],
) -> Optional[SignalData]:
    direction = TrendDirection.from_raw(direction)
    if direction is None:
        return None
    pattern = find_entry_pattern(candles_1h, aoi, direction)
    if not pattern:
        return None

    if pattern.is_break_candle_last:
        break_index = len(pattern.candles) - 1
        after_break_index = None
    else:
        break_index = len(pattern.candles) - 2
        after_break_index = len(pattern.candles) - 1
    trade_quality = evaluate_entry_quality(
        pattern.candles,
        aoi.lower,
        aoi.upper,
        direction,
        0,
        break_index,
        after_break_index,
    )

    return SignalData(
        candles=pattern.candles,
        signal_time=pattern.candles[-1].time,
        trade_quality=trade_quality,
    )
