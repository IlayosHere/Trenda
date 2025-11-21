"""AOI analyzer orchestrator.

This module delegates context building, zone generation, and scoring to
helpers in ``analyzers.aoi`` so the entrypoint stays focused on control flow.
"""

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta

from .trend_analyzer import _check_for_structure_break, _find_corresponding_structural_swing, _find_initial_structure
from configuration import ANALYSIS_PARAMS, TIMEFRAMES, FOREX_PAIRS
from externals.data_fetcher import fetch_data
import externals.db_handler as db_handler
import utils.display as display
from constants import BREAK_BEARISH, BREAK_BULLISH, NO_BREAK, SwingPoint
from utils.forex import get_pip_size, price_to_pips, pips_to_price
from .aoi import (
    apply_directional_weighting_and_classify,
    build_context,
    get_overall_trend,
    extract_swings,
    generate_aoi_zones,
    AOI_CONFIGS,
    AOISettings,
    AOIContext
)


def analyze_aoi_by_timeframe(timeframe: str) -> None:
    settings = AOI_CONFIGS.get(timeframe)
    if settings is None:
        display.print_status(
            f"\n--- ⚠️ Skipping AOI analysis for {timeframe}: no configuration found ---"
        )
        return

    display.print_status(f"\n--- 🔄 Running AOI analysis for {settings.timeframe} ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Processing {symbol}...")
        try:
            db_handler.clear_aois(symbol, timeframe)
            _process_symbol(settings, symbol)
        except Exception as err:
            display.print_error(f"  -> Failed for {symbol}: {err}")


def _process_symbol(settings: AOISettings, symbol: str) -> None:
    trend_direction = get_overall_trend(settings.trend_alignment_timeframes, symbol)

    if (trend_direction == None):
        display.print_status(
            f"  ⚠️ Skipping {symbol}: trends not aligned across {settings.trend_alignment_timeframes}."
        )
        return

    mt5_timeframe = TIMEFRAMES.get(settings.timeframe)
    timeframe_params = ANALYSIS_PARAMS.get(settings.timeframe, {})
    lookback_bars = timeframe_params.get("aoi_lookback")

    data = fetch_data(symbol, mt5_timeframe, int(lookback_bars))
    if data is None or "close" not in data:
        display.print_error(f"  ❌ No price data for {symbol}.")
        return

    prices = np.asarray(data["close"].values)
    last_bar_idx = len(prices) - 1
    current_price = float(prices[-1])
    atr = _calculate_atr(data, symbol)
    context = build_context(settings, symbol, atr)
    
    swings = extract_swings(prices, context)
    important_swings = filter_noisy_points(swings)
    zones = generate_aoi_zones(important_swings, last_bar_idx, context)
    zones_scored = apply_directional_weighting_and_classify(
        zones, current_price, last_bar_idx, trend_direction, context
    )
    top_zones = sorted(zones_scored, key=lambda z: z["score"], reverse=True)[
        : settings.max_zones_per_symbol
    ]

    db_handler.store_aois(symbol, settings.timeframe, top_zones)
    display.print_status(
        f"  ✅ Stored {len(top_zones)} AOIs for {symbol} ({settings.timeframe})."
    ) 

def _calculate_atr(
    data,
    symbol: str
) -> Optional[float]:
    """Derive the price window to scan for AOIs using ATR multiples."""

    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values

    df = pd.DataFrame({
    "high": highs,
    "low": lows,
    "close": closes,
    })

    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    current_atr = df["atr"].iloc[-1]
    pip_size = get_pip_size(symbol)
    return price_to_pips(current_atr, pip_size)

def filter_noisy_points(swings: List[SwingPoint]) -> List[SwingPoint]:
    structual_swing_points = []
    current_high, current_low = _find_initial_structure(swings)
    for index, swing in enumerate(swings):
        strcutual_break = _check_for_structure_break(swing, current_high, current_low)
        if (strcutual_break == BREAK_BULLISH):
            current_low = _find_corresponding_structural_swing(BREAK_BULLISH, index, swings)
            current_high = swing
            structual_swing_points.append(swing)
            if (current_low not in structual_swing_points):
                structual_swing_points.append(current_low)
        elif (strcutual_break == BREAK_BEARISH):
            current_high = _find_corresponding_structural_swing(BREAK_BEARISH, index, swings)
            current_low = swing
            structual_swing_points.append(swing)
            if (current_high not in structual_swing_points):
                structual_swing_points.append(current_high)
           
    return structual_swing_points