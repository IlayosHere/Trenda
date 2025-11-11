"""Public entrypoint and orchestration for AOI analysis."""

from __future__ import annotations

import numpy as np

from data_retriever.configuration import FOREX_PAIRS, TIMEFRAMES
from data_retriever.externals import db_handler
from data_retriever.externals.data_fetcher import fetch_data
from data_retriever.utils import display

from .config import AOI_MAX_ZONES_PER_SYMBOL, AOI_SOURCE_TIMEFRAME, TARGET_TIMEFRAME
from .context import build_context
from .pipeline import generate_aoi_zones
from .scoring import apply_directional_weighting
from .swings import extract_swings
from .trend import determine_trend


def analyze_aoi_by_timeframe(timeframe: str) -> None:
    """Main scheduled AOI computation (restricted to 4H timeframe)."""
    if timeframe != TARGET_TIMEFRAME:
        return

    display.print_status(f"\n--- 🔄 Running AOI analysis for {timeframe} ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Processing {symbol}...")
        try:
            high_price, low_price = db_handler.fetch_trend_levels(symbol, AOI_SOURCE_TIMEFRAME)
            _process_symbol(timeframe, symbol, high_price, low_price)
        except Exception as err:
            display.print_error(f"  -> Failed for {symbol}: {err}")


def _process_symbol(timeframe: str, symbol: str, base_high: float, base_low: float) -> None:
    trend_4h = determine_trend(symbol, "4H")
    trend_1d = determine_trend(symbol, "1D")

    if trend_4h is None or trend_1d is None or trend_4h != trend_1d:
        display.print_status(
            f"  ⚠️ Skipping {symbol}: 4H/1D trends not aligned or unavailable."
        )
        db_handler.store_aois(symbol, timeframe, [])
        return

    context = build_context(timeframe, symbol, base_high, base_low)
    if context is None:
        db_handler.store_aois(symbol, timeframe, [])
        return

    data = fetch_data(symbol, TIMEFRAMES[timeframe], context.params["aoi_lookback"])
    if data is None or "close" not in data:
        display.print_error(f"  ❌ No price data for {symbol}.")
        db_handler.store_aois(symbol, timeframe, [])
        return

    prices = np.asarray(data["close"].values)
    last_bar_idx = len(prices) - 1
    current_price = float(prices[-1])

    swings = extract_swings(prices, context)
    zones = generate_aoi_zones(swings, last_bar_idx, context)
    weighted = apply_directional_weighting(zones, current_price, trend_4h)

    top_zones = sorted(weighted, key=lambda zone: zone["score"], reverse=True)[
        :AOI_MAX_ZONES_PER_SYMBOL
    ]

    db_handler.store_aois(symbol, timeframe, top_zones)
    display.print_status(f"  ✅ Stored {len(top_zones)} AOIs for {symbol}.")


__all__ = ["analyze_aoi_by_timeframe"]
