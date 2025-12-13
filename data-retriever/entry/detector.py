from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from configuration import FOREX_PAIRS, TIMEFRAMES, require_analysis_params
from entry.pattern_finder import find_entry_pattern
from entry.quality import evaluate_entry_quality, QualityResult
from entry.sl_calculator import compute_aoi_sl_distances
from aoi.aoi_repository import fetch_tradable_aois
from entry.signal_repository import store_entry_signal_with_symbol
from externals.data_fetcher import fetch_data
from models import AOIZone, TrendDirection
from models.market import Candle, SignalData
from trend.bias import get_overall_trend, get_trend_by_timeframe
from utils.indicators import calculate_atr
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

        # Calculate trend alignment strength (count of trends matching the direction)
        trend_alignment_strength = _calculate_trend_alignment_strength(
            trend_snapshot, direction
        )
        
        # Calculate 1H ATR
        atr_1h = calculate_atr(candles)

        for aoi in aois:
            signal = scan_1h_for_entry(
                symbol=symbol,
                direction=direction,
                aoi=aoi,
                candles_1h=candles,
                trend_snapshot=trend_snapshot,
                trend_alignment_strength=trend_alignment_strength,
                atr_1h=atr_1h,
            )
            if signal:
                entry_id = store_entry_signal_with_symbol(symbol, signal)
                if entry_id:
                    display.print_status(
                        f"    ✅ Entry signal {entry_id} ({signal.quality_result.tier}) "
                        f"for {symbol} at AOI {aoi.lower}-{aoi.upper} "
                        f"(score: {signal.quality_result.final_score:.2f})"
                    )


def _collect_trend_snapshot(
    timeframes: Sequence[str], symbol: str
) -> Mapping[str, Optional[TrendDirection]]:
    return {tf: get_trend_by_timeframe(symbol, tf) for tf in timeframes}


def _calculate_trend_alignment_strength(
    trend_snapshot: Mapping[str, Optional[TrendDirection]],
    direction: TrendDirection,
) -> int:
    """Count how many timeframes align with the given direction."""
    count = 0
    for tf_trend in trend_snapshot.values():
        if tf_trend == direction:
            count += 1
    return count


def _get_trend_value(
    trend_snapshot: Mapping[str, Optional[TrendDirection]], 
    timeframe: str
) -> str:
    """Get the trend value as a string for a specific timeframe."""
    trend = trend_snapshot.get(timeframe)
    if trend is None:
        return "neutral"
    return trend.value


def scan_1h_for_entry(
    symbol: str,
    direction: TrendDirection,
    aoi: AOIZone,
    candles_1h: Union[pd.DataFrame, Sequence[Union[Candle, Mapping[str, Any]]]],
    trend_snapshot: Mapping[str, Optional[TrendDirection]],
    trend_alignment_strength: int,
    atr_1h: float,
) -> Optional[SignalData]:
    """Scan for entry patterns and build complete SignalData if found."""
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
    
    quality_result = evaluate_entry_quality(
        pattern.candles,
        aoi.lower,
        aoi.upper,
        direction,
        0,
        break_index,
        after_break_index,
    )

    # Entry price is the close of the last candle (break or after-break)
    entry_price = pattern.candles[-1].close

    # Compute AOI-based stop loss distances
    sl_data = compute_aoi_sl_distances(
        direction=direction,
        entry_price=entry_price,
        aoi_low=aoi.lower,
        aoi_high=aoi.upper,
        atr_1h=atr_1h,
    )

    return SignalData(
        candles=pattern.candles,
        signal_time=pattern.candles[-1].time,
        direction=direction,
        # Trend snapshot
        trend_4h=_get_trend_value(trend_snapshot, "4H"),
        trend_1d=_get_trend_value(trend_snapshot, "1D"),
        trend_1w=_get_trend_value(trend_snapshot, "1W"),
        trend_alignment_strength=trend_alignment_strength,
        # AOI snapshot
        aoi_timeframe=aoi.timeframe,
        aoi_low=aoi.lower,
        aoi_high=aoi.upper,
        aoi_classification=aoi.classification,
        # Entry context
        entry_price=entry_price,
        atr_1h=atr_1h,
        # Scoring
        quality_result=quality_result,
        # Meta
        is_break_candle_last=pattern.is_break_candle_last,
        # SL distances
        aoi_sl_tolerance_atr=sl_data.aoi_sl_tolerance_atr,
        aoi_raw_sl_distance_price=sl_data.aoi_raw_sl_distance_price,
        aoi_raw_sl_distance_atr=sl_data.aoi_raw_sl_distance_atr,
        aoi_effective_sl_distance_price=sl_data.aoi_effective_sl_distance_price,
        aoi_effective_sl_distance_atr=sl_data.aoi_effective_sl_distance_atr,
    )

