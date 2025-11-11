"""Helpers for preparing AOI analysis context."""

from __future__ import annotations

from typing import Optional
import numpy as np

from data_retriever.configuration import ANALYSIS_PARAMS
from data_retriever.utils import display
from data_retriever.utils.forex import (
    get_pip_size,
    normalize_price_range,
    price_to_pips,
    pips_to_price,
)

from .config import (
    AOI_BOUND_TOLERANCE_RATIO,
    AOI_MIN_HEIGHT_PIPS_FLOOR,
    AOI_MIN_HEIGHT_RATIO,
    AOI_MIN_RANGE_PIPS,
    AOI_MAX_HEIGHT_MAX_PIPS,
    AOI_MAX_HEIGHT_MIN_PIPS,
    AOI_MAX_HEIGHT_RATIO,
    TARGET_TIMEFRAME,
)
from .models import AOIContext


def build_context(timeframe: str, symbol: str, base_high: float, base_low: float) -> Optional[AOIContext]:
    """Prepare analysis context and skip invalid cases."""
    lower, upper = normalize_price_range(base_low, base_high)
    pip_size = get_pip_size(symbol)
    price_range = upper - lower
    base_range_pips = price_to_pips(price_range, pip_size)

    if base_range_pips < AOI_MIN_RANGE_PIPS:
        display.print_status(
            f"  ⚠️ Skipping {symbol}: 4H range too small ({base_range_pips:.1f} pips)."
        )
        return None

    params = ANALYSIS_PARAMS[TARGET_TIMEFRAME]

    min_height_pips = max(AOI_MIN_HEIGHT_PIPS_FLOOR, base_range_pips * AOI_MIN_HEIGHT_RATIO)
    max_height_pips = np.clip(
        base_range_pips * AOI_MAX_HEIGHT_RATIO,
        AOI_MAX_HEIGHT_MIN_PIPS,
        AOI_MAX_HEIGHT_MAX_PIPS,
    )

    min_height_price = pips_to_price(min_height_pips, pip_size)
    max_height_price = pips_to_price(max_height_pips, pip_size)
    tolerance_price = pips_to_price(base_range_pips * AOI_BOUND_TOLERANCE_RATIO, pip_size)

    return AOIContext(
        symbol=symbol,
        base_low=lower,
        base_high=upper,
        pip_size=pip_size,
        base_range_pips=base_range_pips,
        min_height_price=min_height_price,
        max_height_price=max_height_price,
        tolerance_price=tolerance_price,
        params=params,
    )


__all__ = ["build_context"]
