from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

import utils.display as display
from configuration import ANALYSIS_PARAMS
from .aoi import AOISettings
from utils.forex import (
    get_pip_size,
    normalize_price_range,
    price_to_pips,
    pips_to_price,
)
from ..trend_analyzer import get_swing_points


@dataclass
class AOIContext:
    symbol: str
    timeframe: str
    base_low: float
    base_high: float
    pip_size: float
    base_range_pips: float
    min_height_price: float
    max_height_price: float
    tolerance_price: float
    params: Dict[str, float]
    settings: AOISettings


def build_context(
    settings: AOISettings, symbol: str, base_high: float, base_low: float
) -> Optional["AOIContext"]:
    """Prepare the AOI analysis context for a symbol and timeframe."""

    params = ANALYSIS_PARAMS.get(settings.timeframe)

    lower, upper = normalize_price_range(base_low, base_high)
    pip_size = get_pip_size(symbol)
    price_range = upper - lower
    base_range_pips = price_to_pips(price_range, pip_size)

    # Skip if base range too small for configured timeframe
    if base_range_pips < settings.min_range_pips:
        display.print_status(
            f"  ⚠️ Skipping {symbol}: range too small ({base_range_pips:.1f} pips)."
        )
        return None

    # --- Dynamic AOI height limits ---
    min_height_pips = max(
        settings.min_height_pips_floor, base_range_pips * settings.min_height_ratio
    )
    max_height_pips = np.clip(
        base_range_pips * settings.max_height_ratio,
        settings.max_height_min_pips,
        settings.max_height_max_pips,
    )

    min_height_price = pips_to_price(min_height_pips, pip_size)
    max_height_price = pips_to_price(max_height_pips, pip_size)
    tolerance_price = pips_to_price(
        base_range_pips * settings.bound_tolerance_ratio, pip_size
    )

    return AOIContext(
        timeframe=settings.timeframe,
        symbol=symbol,
        base_low=lower,
        base_high=upper,
        pip_size=pip_size,
        base_range_pips=base_range_pips,
        min_height_price=min_height_price,
        max_height_price=max_height_price,
        tolerance_price=tolerance_price,
        params=params,
        settings=settings,
    )


def extract_swings(prices: np.ndarray, context: AOIContext):
    """Detect swing highs/lows using configured prominence and distance."""

    return get_swing_points(
        prices, context.params["distance"], context.params["prominence"]
    )
