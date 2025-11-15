"""AOI analyzer orchestrator.

This module delegates context building, zone generation, and scoring to
helpers in ``analyzers.aoi`` so the entrypoint stays focused on control flow.
"""

from typing import List, Optional, Tuple

import numpy as np
import talib

from configuration import ANALYSIS_PARAMS, TIMEFRAMES, FOREX_PAIRS
from externals.data_fetcher import fetch_data
import externals.db_handler as db_handler
import utils.display as display
from constants import SwingPoint
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
    """Main scheduled AOI computation driven by timeframe-specific configuration."""
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
    """Execute the AOI pipeline for a single symbol."""

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

    bounds = _calculate_atr_window_bounds(
        data, symbol, current_price, settings
    )
    if bounds is None:
        display.print_error(
            f"  ⚠️ Skipping {symbol}: unable to determine ATR-based bounds."
        )
        return

    base_low, base_high = bounds

    context = build_context(settings, symbol, base_high, base_low)
    if context is None:
        return

    swings = extract_swings(prices, context)
    relevant_swings = filter_irrelvant_swings(swings, context)
    zones = generate_aoi_zones(relevant_swings, last_bar_idx, trend_direction, context)

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
    
def filter_irrelvant_swings(swings: List[SwingPoint], context: AOIContext):
    relevant_swings = []
    for swing in swings:
        if (swing[1] <= context.extended_upper and swing[1] >= context.extended_lower):
            relevant_swings.append(swing)
    return relevant_swings


def _calculate_atr_window_bounds(
    data,
    symbol: str,
    current_price: float,
    settings: AOISettings,
) -> Optional[Tuple[float, float]]:
    """Derive the price window to scan for AOIs using ATR multiples."""

    required_cols = {"high", "low", "close"}
    if not required_cols.issubset(data.columns):
        display.print_error(
            f"  ❌ Missing columns {required_cols - set(data.columns)} for ATR calculation."
        )
        return None

    highs = data["high"].values
    lows = data["low"].values
    closes = data["close"].values

    atr_values = talib.ATR(
        highs,
        lows,
        closes,
        timeperiod=settings.atr_period,
    )

    if atr_values is None or len(atr_values) == 0:
        return None

    latest_atr = float(atr_values[-1])
    if np.isnan(latest_atr) or latest_atr <= 0:
        return None

    pip_size = get_pip_size(symbol)
    atr_pips = price_to_pips(latest_atr, pip_size)
    window_pips = atr_pips * settings.atr_window_multiplier

    if window_pips <= 0:
        return None

    window_price = pips_to_price(window_pips, pip_size)
    return current_price - window_price, current_price + window_price
