from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from configuration import ANALYSIS_PARAMS, TIMEFRAMES
from externals.data_fetcher import fetch_data
import externals.db_handler as db_handler
import utils.display as display
from .trend_analyzer import get_swing_points
from utils.forex import (
    get_pip_size,
    normalize_price_range,
    price_to_pips,
    pips_to_price,
)


AOI_TIMEFRAME = "30min"
AOI_SOURCE_TIMEFRAME = "4H"
AOI_MIN_TOUCHES = 3
AOI_MIN_HEIGHT_RATIO = 0.05
AOI_MAX_HEIGHT_RATIO = 0.10


@dataclass
class AOIContext:
    symbol: str
    base_low: float
    base_high: float
    pip_size: float
    base_range_pips: float
    min_height_price: float
    max_height_price: float
    params: Dict[str, float]


def find_and_store_aois(symbol: str, base_high: float, base_low: float) -> None:
    """Detect and persist areas of interest for a symbol."""

    context = _build_context(symbol, base_high, base_low)
    if context is None:
        return

    prices = _load_close_prices(symbol, context)
    if prices is None:
        db_handler.store_aois(symbol, AOI_TIMEFRAME, [], context.base_range_pips)
        return

    swings = _extract_swings(prices, context)
    zones = _detect_aois_from_swings(swings, context)

    db_handler.store_aois(symbol, AOI_TIMEFRAME, zones, context.base_range_pips)

    display.print_status(
        f"  -> {symbol}: Detected {len(zones)} AOI zone(s) on {AOI_TIMEFRAME}."
    )


def _build_context(symbol: str, base_high: float, base_low: float) -> Optional[AOIContext]:
    if AOI_TIMEFRAME not in ANALYSIS_PARAMS or AOI_TIMEFRAME not in TIMEFRAMES:
        display.print_error(
            f"AOI timeframe '{AOI_TIMEFRAME}' missing from configuration. Skipping AOI detection."
        )
        return None

    lower, upper = normalize_price_range(base_low, base_high)
    price_range = upper - lower
    if price_range <= 0:
        display.print_error(
            f"AOI base range invalid for {symbol}. High ({base_high}) must be greater than low ({base_low})."
        )
        return None

    pip_size = get_pip_size(symbol)
    base_range_pips = price_to_pips(price_range, pip_size)
    params = ANALYSIS_PARAMS[AOI_TIMEFRAME]

    min_height_price = pips_to_price(base_range_pips * AOI_MIN_HEIGHT_RATIO, pip_size)
    max_height_price = pips_to_price(base_range_pips * AOI_MAX_HEIGHT_RATIO, pip_size)

    if min_height_price <= 0 or pip_size <= 0:
        display.print_error(
            f"AOI configuration invalid for {symbol}. Computed minimum height is non-positive."
        )
        return None

    return AOIContext(
        symbol=symbol,
        base_low=lower,
        base_high=upper,
        pip_size=pip_size,
        base_range_pips=base_range_pips,
        min_height_price=min_height_price,
        max_height_price=max_height_price,
        params=params,
    )


def _load_close_prices(symbol: str, context: AOIContext) -> Optional[np.ndarray]:
    timeframe_mt5 = TIMEFRAMES[AOI_TIMEFRAME]
    data = fetch_data(symbol, timeframe_mt5, context.params["lookback"])

    if data is None or data.empty:
        display.print_error(
            f"  -> {symbol}: No data returned for AOI timeframe {AOI_TIMEFRAME}."
        )
        return None

    return np.asarray(data["close"].values)


def _extract_swings(prices: np.ndarray, context: AOIContext) -> List:
    return get_swing_points(
        prices, context.params["distance"], context.params["prominence"]
    )


def _detect_aois_from_swings(
    swings: List, context: AOIContext
) -> List[Dict[str, float]]:
    if not swings:
        return []

    sorted_swings = sorted(swings, key=lambda swing: swing[1])
    aois: Dict[tuple, Dict[str, float]] = {}

    for start_index in range(len(sorted_swings)):
        cluster = [sorted_swings[start_index]]

        for end_index in range(start_index + 1, len(sorted_swings)):
            cluster.append(sorted_swings[end_index])
            cluster_height = cluster[-1][1] - cluster[0][1]

            if cluster_height > context.max_height_price:
                break

            if (
                len(cluster) < AOI_MIN_TOUCHES
                or cluster_height < context.min_height_price
            ):
                continue

            lower_bound = cluster[0][1]
            upper_bound = cluster[-1][1]
            key = (
                round(lower_bound / context.pip_size, 5),
                round(upper_bound / context.pip_size, 5),
            )

            if key not in aois:
                aois[key] = {
                    "lower_bound": lower_bound,
                    "upper_bound": upper_bound,
                    "touches": float(len(cluster)),
                    "height_pips": price_to_pips(
                        cluster_height, context.pip_size
                    ),
                }
            else:
                aois[key]["touches"] = max(
                    aois[key]["touches"], float(len(cluster))
                )

    return list(aois.values())

