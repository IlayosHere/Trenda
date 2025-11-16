from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

import utils.display as display
from configuration import ANALYSIS_PARAMS
from .aoi_configuration import AOISettings
from utils.forex import (
    get_pip_size,
    price_to_pips,
    pips_to_price,
)
from ..trend_analyzer import get_swing_points


@dataclass
class AOIContext:
    symbol: str
    timeframe: str
    pip_size: float
    min_height_price: float
    max_height_price: float
    params: Dict[str, float]
    settings: AOISettings


def build_context(
    settings: AOISettings, symbol: str, atr_window: float) -> Optional["AOIContext"]:
    """Prepare the AOI analysis context for a symbol and timeframe."""

    params = ANALYSIS_PARAMS.get(settings.timeframe)

    pip_size = get_pip_size(symbol)

    # --- Dynamic AOI height limits ---
    min_height_pips = max(
        settings.min_height_pips_floor, atr_window * settings.min_height_ratio
    )
    max_height_pips = max(
        atr_window * settings.max_height_ratio,
        settings.max_heihgt_pips_floor
    )

    min_height_price = pips_to_price(min_height_pips, pip_size)
    max_height_price = pips_to_price(max_height_pips, pip_size)
    return AOIContext(
        timeframe=settings.timeframe,
        symbol=symbol,
        pip_size=pip_size,
        min_height_price=min_height_price,
        max_height_price=max_height_price,
        params=params,
        settings=settings,
    )


def extract_swings(prices: np.ndarray, context: AOIContext):
    """Detect swing highs/lows using configured prominence and distance."""

    return get_swing_points(
        prices, context.params["distance"], context.params["prominence"]
    )
