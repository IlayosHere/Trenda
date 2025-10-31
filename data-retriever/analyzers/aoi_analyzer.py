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


@dataclass
class AOIZoneCandidate:
    lower_bound: float
    upper_bound: float
    height: float
    touches: int


def find_and_store_aois(symbol: str, base_high: float, base_low: float) -> None:
    """Detect and persist areas of interest for a symbol."""

    context = _build_context(symbol, base_high, base_low)
    if context is None:
        return

    prices = _load_close_prices(symbol, context)
    if prices is None:
        db_handler.store_aois(symbol, AOI_TIMEFRAME, [])
        return

    swings = _extract_swings(prices, context)
    zones = _detect_aois_from_swings(swings, context)

    db_handler.store_aois(symbol, AOI_TIMEFRAME, zones)

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

    price_sorted = sorted(swing[1] for swing in swings)
    zone_candidates: Dict[tuple, AOIZoneCandidate] = {}
    swing_count = len(price_sorted)

    for start_index in range(swing_count):
        lower_price = price_sorted[start_index]

        for end_index in range(start_index + AOI_MIN_TOUCHES - 1, swing_count):
            upper_price = price_sorted[end_index]
            height = upper_price - lower_price

            if height > context.max_height_price:
                break

            touches = end_index - start_index + 1
            if touches < AOI_MIN_TOUCHES or height < context.min_height_price:
                continue

            key = (
                round(lower_price / context.pip_size, 5),
                round(upper_price / context.pip_size, 5),
            )

            existing = zone_candidates.get(key)
            if not existing or (
                touches > existing.touches
                or (touches == existing.touches and height > existing.height)
            ):
                zone_candidates[key] = AOIZoneCandidate(
                    lower_bound=lower_price,
                    upper_bound=upper_price,
                    height=height,
                    touches=touches,
                )

    filtered = _filter_overlapping_zones(list(zone_candidates.values()))
    return [
        {"lower_bound": zone.lower_bound, "upper_bound": zone.upper_bound}
        for zone in filtered
    ]


def _filter_overlapping_zones(zones: List[AOIZoneCandidate]) -> List[AOIZoneCandidate]:
    if not zones:
        return []

    sorted_zones = sorted(
        zones, key=lambda zone: (zone.height, zone.touches), reverse=True
    )

    selected: List[AOIZoneCandidate] = []
    for zone in sorted_zones:
        if not any(_zones_overlap(zone, existing) for existing in selected):
            selected.append(zone)

    return sorted(selected, key=lambda zone: zone.lower_bound)


def _zones_overlap(zone_a: AOIZoneCandidate, zone_b: AOIZoneCandidate) -> bool:
    return not (
        zone_a.upper_bound <= zone_b.lower_bound
        or zone_a.lower_bound >= zone_b.upper_bound
    )

