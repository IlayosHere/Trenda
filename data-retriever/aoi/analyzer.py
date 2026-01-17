"""AOI analyzer orchestrator.

This module delegates context building, zone generation, and scoring to
helpers in the ``aoi`` package so the entrypoint stays focused on control flow.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from utils.indicators import calculate_atr

from constants import BREAK_BEARISH, BREAK_BULLISH, SwingPoint
from models import TrendDirection
from configuration import (
    require_aoi_lookback,
    require_analysis_params,
)
from aoi.aoi_repository import clear_aois, store_aois
from logger import get_logger

logger = get_logger(__name__)
from utils.forex import get_pip_size, price_to_pips
from trend.structure import (
    _check_for_structure_break,
    _find_corresponding_structural_swing,
    _find_initial_structure,
)
from aoi.aoi_configuration import AOI_CONFIGS, AOISettings
from aoi.context import build_context, extract_swings
from aoi.pipeline import generate_aoi_zones
from aoi.scoring import apply_directional_weighting_and_classify
from trend.bias import get_overall_trend


def analyze_single_symbol_aoi(
    symbol: str, timeframe: str, data: pd.DataFrame | None
) -> None:
    settings = AOI_CONFIGS.get(timeframe)
    if settings is None:

        logger.info(
            f"\n--- ⚠️ Skipping AOI analysis for {timeframe}: no configuration found ---"
        )
        return

    logger.info(f"\n--- 🔄 Running AOI analysis for {symbol}/{timeframe} ---")
    
    try:
        clear_aois(symbol, timeframe)
        if data is None:
            logger.error(
                f"  ❌ No candle data provided for {symbol} on {timeframe}."
            )
            return
        _process_symbol(settings, symbol, data)
    except Exception as err:
        logger.error(f"  -> Failed for {symbol}: {err}")


def _process_symbol(settings: AOISettings, symbol: str, data: pd.DataFrame) -> None:
    trend_direction = TrendDirection.from_raw(
        get_overall_trend(settings.trend_alignment_timeframes, symbol)
    )

    if trend_direction is None:
        logger.info(
            f"  ⚠️ Skipping {symbol}: trends not aligned across {settings.trend_alignment_timeframes}."
        )
        return

    require_analysis_params(settings.timeframe)
    require_aoi_lookback(settings.timeframe)

    if data is None or "close" not in data:
        logger.error(f"  ❌ No price data for {symbol}.")
        return

    prices = np.asarray(data["close"].values)
    last_bar_idx = len(prices) - 1
    current_price = float(prices[-1])
    atr = _calculate_atr_in_pips(data, symbol)
    context = build_context(settings, symbol, atr)
    
    swings = extract_swings(prices, context)
    important_swings = filter_noisy_points(swings)
    zones = generate_aoi_zones(important_swings, last_bar_idx, context)
    zones_scored = apply_directional_weighting_and_classify(
        zones, current_price, trend_direction, context
    )
    top_zones = sorted(zones_scored, key=lambda z: z.score or 0.0, reverse=True)[
        : settings.max_zones_per_symbol
    ]

    store_aois(symbol, settings.timeframe, top_zones)
    logger.info(
        f"  ✅ Stored {len(top_zones)} AOIs for {symbol} ({settings.timeframe})."
    )

def _calculate_atr_in_pips(
    data,
    symbol: str
) -> Optional[float]:
    """Calculate ATR and convert to pips for AOI context building."""
    current_atr = calculate_atr(data, length=14)
    if current_atr == 0.0:
        return None
    pip_size = get_pip_size(symbol)
    return price_to_pips(current_atr, pip_size)

def filter_noisy_points(swings: List[SwingPoint]) -> List[SwingPoint]:
    structural_swing_points = []
    current_high, current_low = _find_initial_structure(swings)
    for index, swing in enumerate(swings):
        structural_break = _check_for_structure_break(swing, current_high, current_low)
        if (structural_break == BREAK_BULLISH):
            current_low = _find_corresponding_structural_swing(BREAK_BULLISH, index, swings)
            current_high = swing
            structural_swing_points.append(swing)
            if (current_low not in structural_swing_points):
                structural_swing_points.append(current_low)
        elif (structural_break == BREAK_BEARISH):
            current_high = _find_corresponding_structural_swing(BREAK_BEARISH, index, swings)
            current_low = swing
            structural_swing_points.append(swing)
            if (current_high not in structural_swing_points):
                structural_swing_points.append(current_high)
           
    return structural_swing_points
