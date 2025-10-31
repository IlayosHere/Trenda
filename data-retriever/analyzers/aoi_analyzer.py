from typing import Dict, List

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
AOI_MIN_TOUCHES = 3
AOI_MIN_HEIGHT_RATIO = 0.05
AOI_MAX_HEIGHT_RATIO = 0.10


def find_and_store_aois(symbol: str, base_high: float, base_low: float) -> None:
    """Detect and persist areas of interest for a symbol.

    Args:
        symbol: Forex symbol (e.g. "EURUSD").
        base_high: The structural high from the higher timeframe (4H).
        base_low: The structural low from the higher timeframe (4H).
    """

    if AOI_TIMEFRAME not in ANALYSIS_PARAMS or AOI_TIMEFRAME not in TIMEFRAMES:
        display.print_error(
            f"AOI timeframe '{AOI_TIMEFRAME}' missing from configuration. Skipping AOI detection."
        )
        return

    lower, upper = normalize_price_range(base_low, base_high)
    price_range = upper - lower
    if price_range <= 0:
        display.print_error(
            f"AOI base range invalid for {symbol}. High ({base_high}) must be greater than low ({base_low})."
        )
        return

    pip_size = get_pip_size(symbol)
    base_range_pips = price_to_pips(price_range, pip_size)

    params = ANALYSIS_PARAMS[AOI_TIMEFRAME]
    timeframe_mt5 = TIMEFRAMES[AOI_TIMEFRAME]
    data = fetch_data(symbol, timeframe_mt5, params["lookback"])

    if data is None or data.empty:
        display.print_error(
            f"  -> {symbol}: No data returned for AOI timeframe {AOI_TIMEFRAME}."
        )
        db_handler.store_aois(symbol, AOI_TIMEFRAME, [], base_range_pips)
        return

    prices = data["close"].values
    swings = get_swing_points(
        np.asarray(prices), params["distance"], params["prominence"]
    )

    aois = _detect_aois_from_swings(swings, base_range_pips, pip_size)

    db_handler.store_aois(symbol, AOI_TIMEFRAME, aois, base_range_pips)

    display.print_status(
        f"  -> {symbol}: Detected {len(aois)} AOI zone(s) on {AOI_TIMEFRAME}."
    )


def _detect_aois_from_swings(
    swings: List, base_range_pips: float, pip_size: float
) -> List[Dict[str, float]]:
    if not swings or base_range_pips <= 0 or pip_size <= 0:
        return []

    min_height_pips = base_range_pips * AOI_MIN_HEIGHT_RATIO
    max_height_pips = base_range_pips * AOI_MAX_HEIGHT_RATIO

    if min_height_pips <= 0:
        return []

    min_height_price = pips_to_price(min_height_pips, pip_size)
    max_height_price = pips_to_price(max_height_pips, pip_size)

    sorted_swings = sorted(swings, key=lambda swing: swing[1])
    aois: Dict[tuple, Dict[str, float]] = {}

    for start_index in range(len(sorted_swings)):
        cluster = [sorted_swings[start_index]]

        for end_index in range(start_index + 1, len(sorted_swings)):
            cluster.append(sorted_swings[end_index])
            cluster_height = cluster[-1][1] - cluster[0][1]

            if cluster_height > max_height_price:
                break

            if len(cluster) < AOI_MIN_TOUCHES or cluster_height < min_height_price:
                continue

            lower_bound = cluster[0][1]
            upper_bound = cluster[-1][1]
            key = (
                round(lower_bound / pip_size, 5),
                round(upper_bound / pip_size, 5),
            )

            if key not in aois:
                aois[key] = {
                    "lower_bound": lower_bound,
                    "upper_bound": upper_bound,
                    "touches": float(len(cluster)),
                    "height_pips": price_to_pips(cluster_height, pip_size),
                }
            else:
                aois[key]["touches"] = max(
                    aois[key]["touches"], float(len(cluster))
                )

    return list(aois.values())

