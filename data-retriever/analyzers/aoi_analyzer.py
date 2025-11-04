from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from configuration import ANALYSIS_PARAMS, TIMEFRAMES, FOREX_PAIRS
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

AOI_SOURCE_TIMEFRAME = "4H"
AOI_MIN_TOUCHES = 3
AOI_MIN_HEIGHT_RATIO = 0.05
AOI_MAX_HEIGHT_RATIO = 0.20


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


def analyze_aoi_by_timeframe(timeframe: str) -> None:
    display.print_status(f"\n--- 🔄 Running scheduled job for {timeframe} ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Updating {symbol} for {timeframe}...")
        
        try:
            high_price, low_price = db_handler.fetch_trend_levels(symbol, AOI_SOURCE_TIMEFRAME)
            find_and_store_aois(timeframe, symbol, high_price, low_price)
            
        except Exception as aoi_error:
            display.print_error(f"  -> Failed to compute AOI for {symbol}: {aoi_error}")

def find_and_store_aois(timeframe, symbol: str, base_high: float, base_low: float) -> None:
    """Detect and persist areas of interest for a symbol."""

    context = _build_context(timeframe, symbol, base_high, base_low)
    if context is None:
        return

    prices = _load_close_prices(timeframe, symbol, context)
    if prices is None:
        db_handler.store_aois(symbol, timeframe, [])
        return

    swings = _extract_swings(prices, context)
    zones = _detect_aois_from_swings(swings, context)

    db_handler.store_aois(symbol, timeframe, zones)
    
    display.print_status(f"Stored AOI for {symbol}.")


def _build_context(timeframe: str, symbol: str, base_high: float, base_low: float) -> Optional[AOIContext]:
    lower, upper = normalize_price_range(base_low, base_high)
    price_range = upper - lower
    pip_size = get_pip_size(symbol)
    base_range_pips = price_to_pips(price_range, pip_size)
    params = ANALYSIS_PARAMS[timeframe]

    min_height_price = pips_to_price(base_range_pips * AOI_MIN_HEIGHT_RATIO, pip_size)
    max_height_price = pips_to_price(base_range_pips * AOI_MAX_HEIGHT_RATIO, pip_size)

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


def _load_close_prices(timeframe, symbol: str, context: AOIContext) -> Optional[np.ndarray]:
    timeframe_config = TIMEFRAMES[timeframe]
    data = fetch_data(symbol, timeframe_config, context.params["lookback"])
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

            if lower_price < context.base_low or upper_price > context.base_high:
                break
            
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
        {"lower_bound": float(zone.lower_bound), "upper_bound": float(zone.upper_bound)}
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

