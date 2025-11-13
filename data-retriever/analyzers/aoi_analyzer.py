"""AOI analyzer orchestrator.

This module delegates context building, zone generation, and scoring to
helpers in ``analyzers.aoi`` so the entrypoint stays focused on control flow.
"""

import numpy as np

from configuration import ANALYSIS_PARAMS, TIMEFRAMES, FOREX_PAIRS, AOI_CONFIGS
from configuration.aoi import AOISettings
from externals.data_fetcher import fetch_data
import externals.db_handler as db_handler
import utils.display as display
from .aoi import (
    apply_directional_weighting_and_classify,
    build_context,
    determine_trend,
    extract_swings,
    generate_aoi_zones,
)


def analyze_aoi_by_timeframe(timeframe: str) -> None:
    """Main scheduled AOI computation driven by timeframe-specific configuration."""

    settings = AOI_CONFIGS.get(timeframe)
    if settings is None:
        display.print_status(
            f"\n--- ⚠️ Skipping AOI analysis for {timeframe}: no configuration found ---"
        )
        return

    display.print_status(f"\n--- 🔄 Running AOI analysis for {settings.target_timeframe} ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Processing {symbol}...")
        try:
            high_price, low_price = db_handler.fetch_trend_levels(
                symbol, settings.source_timeframe
            )
            _process_symbol(settings, symbol, high_price, low_price)
        except Exception as err:
            display.print_error(f"  -> Failed for {symbol}: {err}")


def _process_symbol(settings: AOISettings, symbol: str, base_high: float, base_low: float) -> None:
    """Execute the AOI pipeline for a single symbol."""

    trend_values = [
        determine_trend(symbol, tf) for tf in settings.trend_alignment_timeframes
    ]

    if not trend_values or any(trend is None for trend in trend_values):
        display.print_status(
            f"  ⚠️ Skipping {symbol}: missing trend data for {settings.trend_alignment_timeframes}."
        )
        db_handler.store_aois(symbol, settings.target_timeframe, [])
        return

    if len(set(trend_values)) != 1:
        display.print_status(
            f"  ⚠️ Skipping {symbol}: trends not aligned across {settings.trend_alignment_timeframes}."
        )
        db_handler.store_aois(symbol, settings.target_timeframe, [])
        return

    trend_direction = trend_values[0]

    context = build_context(settings, symbol, base_high, base_low)
    if context is None:
        db_handler.store_aois(symbol, settings.target_timeframe, [])
        return

    mt5_timeframe = TIMEFRAMES.get(settings.target_timeframe)
    timeframe_params = ANALYSIS_PARAMS.get(settings.target_timeframe, {})
    lookback_bars = timeframe_params.get("aoi_lookback") or timeframe_params.get("lookback")

    if mt5_timeframe is None:
        display.print_error(
            f"  ❌ No MT5 timeframe mapping for {settings.target_timeframe}."
        )
        db_handler.store_aois(symbol, settings.target_timeframe, [])
        return

    if lookback_bars is None:
        display.print_error(
            f"  ❌ Missing lookback configuration for {settings.target_timeframe}."
        )
        db_handler.store_aois(symbol, settings.target_timeframe, [])
        return

    data = fetch_data(symbol, mt5_timeframe, int(lookback_bars))
    if data is None or "close" not in data:
        display.print_error(f"  ❌ No price data for {symbol}.")
        db_handler.store_aois(symbol, settings.target_timeframe, [])
        return

    prices = np.asarray(data["close"].values)
    last_bar_idx = len(prices) - 1
    current_price = float(prices[-1])

    swings = extract_swings(prices, context)
    zones = generate_aoi_zones(swings, last_bar_idx, context)

    zones_scored = apply_directional_weighting_and_classify(
        zones, current_price, last_bar_idx, trend_direction, context
    )

    top_zones = sorted(zones_scored, key=lambda z: z["score"], reverse=True)[
        : settings.max_zones_per_symbol
    ]

    db_handler.store_aois(symbol, settings.target_timeframe, top_zones)
    display.print_status(
        f"  ✅ Stored {len(top_zones)} AOIs for {symbol} ({settings.target_timeframe})."
    )
