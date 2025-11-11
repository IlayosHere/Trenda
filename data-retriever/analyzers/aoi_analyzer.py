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

# ==========================================================
#                     CONFIGURATION
# ==========================================================
AOI_SOURCE_TIMEFRAME = "4H"
TARGET_TIMEFRAME = "4H"

# Core rules
AOI_MIN_TOUCHES = 3
AOI_MIN_RANGE_PIPS = 30
AOI_MIN_SWING_GAP_BARS = 3          # temporal spacing between swing touches (1H bars)
AOI_OVERLAP_TOLERANCE_PIPS = 2.0    # merge/overlap tolerance
AOI_MAX_AGE_DAYS = 2
AOI_MAX_AGE_BARS = int((AOI_MAX_AGE_DAYS * 24) / 4)  # convert to 4H bars
AOI_MAX_ZONES_PER_SYMBOL = 3        # keep top 3 overall (tradable bias via weighting)

# Dynamic sizing
AOI_MIN_HEIGHT_RATIO = 0.05          # 5% of 4H range
AOI_MIN_HEIGHT_PIPS_FLOOR = 8        # absolute minimum AOI height
AOI_MAX_HEIGHT_RATIO = 0.15          # 15% of 4H range
AOI_MAX_HEIGHT_MIN_PIPS = 10
AOI_MAX_HEIGHT_MAX_PIPS = 20

# Dynamic bound tolerance (to catch wicks/fakeouts slightly outside 4H bounds)
AOI_BOUND_TOLERANCE_RATIO = 0.05   # ±5% of 4H range

# Trend alignment weighting (bias for tradable side)
AOI_ALIGNMENT_WEIGHT = 1.25         # 25% bonus for trend-aligned AOIs


# ==========================================================
#                      DATA CLASSES
# ==========================================================
@dataclass
class AOIContext:
    symbol: str
    base_low: float
    base_high: float
    pip_size: float
    base_range_pips: float
    min_height_price: float
    max_height_price: float
    tolerance_price: float
    params: Dict[str, float]



@dataclass
class AOIZoneCandidate:
    lower_bound: float
    upper_bound: float
    height: float
    touches: int
    score: float
    last_swing_idx: int


# ==========================================================
#                   PUBLIC ENTRYPOINT
# ==========================================================
def analyze_aoi_by_timeframe(timeframe: str) -> None:
    """
    Main scheduled AOI computation (restricted to 1H timeframe).
    Adds trend-aware filtering: only compute AOIs if 4H and 1D trends agree.
    """
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


# ==========================================================
#                  HIGH-LEVEL PROCESS FLOW
# ==========================================================
def _process_symbol(timeframe: str, symbol: str, base_high: float, base_low: float) -> None:
    """
    Per-symbol AOI flow:
      1) Trend alignment gate (4H & 1D must agree)
      2) Context build & data load
      3) AOI generation (candidates → filters → scoring)
      4) Direction-weighted scoring + classification
      5) Top-3 overall → store (with 'type': 'tradable' | 'reference')
    """
    trend_4h = _determine_trend(symbol, "4H")
    trend_1d = _determine_trend(symbol, "1D")

    if trend_4h is None or trend_1d is None or trend_4h != trend_1d:
        display.print_status(f"  ⚠️ Skipping {symbol}: 4H/1D trends not aligned or unavailable.")
        db_handler.store_aois(symbol, timeframe, [])
        return

    trend_direction = trend_4h  # 'bullish' or 'bearish'

    context = _build_context(timeframe, symbol, base_high, base_low)
    if context is None:
        return

    data = fetch_data(symbol, TIMEFRAMES[timeframe], context.params["aoi_lookback"])
    if data is None or "close" not in data:
        display.print_error(f"  ❌ No price data for {symbol}.")
        db_handler.store_aois(symbol, timeframe, [])
        return

    prices = np.asarray(data["close"].values)
    last_bar_idx = len(prices) - 1
    current_price = float(prices[-1])

    swings = _extract_swings(prices, context)
    zones = _generate_aoi_zones(swings, last_bar_idx, context)

    # Direction-weighted scoring + type classification (tradable | reference)
    zones_scored = _apply_directional_weighting_and_classify(
        zones, current_price, last_bar_idx, trend_direction, context
    )

    # Keep global top-3 by final score (could be all tradable or all reference)
    top_zones = sorted(zones_scored, key=lambda z: z["score"], reverse=True)[:AOI_MAX_ZONES_PER_SYMBOL]

    db_handler.store_aois(symbol, timeframe, top_zones)
    display.print_status(f"  ✅ Stored {len(top_zones)} AOIs for {symbol}.")


# ==========================================================
#                 CONTEXT & DATA HELPERS
# ==========================================================
def _build_context(timeframe: str, symbol: str, base_high: float, base_low: float) -> Optional[AOIContext]:
    """Prepare analysis context and skip invalid cases."""
    lower, upper = normalize_price_range(base_low, base_high)
    pip_size = get_pip_size(symbol)
    price_range = upper - lower
    base_range_pips = price_to_pips(price_range, pip_size)

    # Skip if 4H range too small
    if base_range_pips < AOI_MIN_RANGE_PIPS:
        display.print_status(f"  ⚠️ Skipping {symbol}: 4H range too small ({base_range_pips:.1f} pips).")
        return None

    params = ANALYSIS_PARAMS[TARGET_TIMEFRAME]

    # --- Dynamic AOI height limits ---
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


def _extract_swings(prices: np.ndarray, context: AOIContext) -> List:
    """Detect swing highs/lows using configured prominence and distance."""
    return get_swing_points(prices, context.params["distance"], context.params["prominence"])


# ==========================================================
#                  AOI GENERATION PIPELINE
# ==========================================================
def _generate_aoi_zones(swings: List, last_bar_idx: int, context: AOIContext) -> List[Dict[str, float]]:
    """
    Full AOI generation:
      - candidates from swings (with time spacing)
      - bounds/size filter
      - merge nearby under cap
      - age filter (≤ 2 days)
      - overlap filter
      - (initial) score based on density, recency, extremity (no direction yet)
    """
    if not swings:
        return []

    candidates = _find_zone_candidates(swings, last_bar_idx, context)
    bounded = _filter_zones_by_bounds(candidates, context)
    merged = _merge_nearby_zones(bounded, context)
    recent = _filter_old_zones_by_bars(merged, last_bar_idx)
    non_overlapping = _filter_overlapping_zones(recent, context)

    # Format for downstream scoring/classification
    return [
        {"lower_bound": z.lower_bound, "upper_bound": z.upper_bound, "height": z.height,
         "touches": z.touches, "score": z.score, "last_swing_idx": z.last_swing_idx}
        for z in non_overlapping
    ]


# ==========================================================
#                   CANDIDATE DETECTION
# ==========================================================
def _find_zone_candidates(swings: List, last_bar_idx: int, context: AOIContext) -> List[AOIZoneCandidate]:
    """
    Identify AOI candidates from swing clustering with time-spacing and base scoring
    (density, recency, extremity). Directional weighting applied later.
    """
    pairs: List[tuple[int, float]] = [(int(s[0]), float(s[1])) for s in swings]
    price_sorted: List[tuple[int, float]] = sorted(pairs, key=lambda x: x[1])

    candidates: Dict[tuple, AOIZoneCandidate] = {}
    total = len(price_sorted)

    for i in range(total):
        lower_idx, lower_price = price_sorted[i]

        for j in range(i + AOI_MIN_TOUCHES - 1, total):
            upper_idx, upper_price = price_sorted[j]
            height = upper_price - lower_price

            # --- Bounds & height constraints ---
            if not _is_zone_within_extended_bounds(lower_price, upper_price, context):
                break

            if height < context.min_height_price or height > context.max_height_price:
                continue

            # --- Collect touches ---
            mid_indices = [idx for (idx, price) in pairs if lower_price <= price <= upper_price]
            if len(mid_indices) < AOI_MIN_TOUCHES:
                continue
            if not _has_sufficient_spacing(mid_indices):
                continue

            last_idx = max(mid_indices)
            base_score = _calculate_base_zone_score(
                lower_price, upper_price, height, len(mid_indices), last_idx, last_bar_idx, context
            )

            key = (round(lower_price / context.pip_size, 5), round(upper_price / context.pip_size, 5))
            existing = candidates.get(key)
            if not existing or base_score > existing.score:
                candidates[key] = AOIZoneCandidate(
                    lower_bound=lower_price,
                    upper_bound=upper_price,
                    height=height,
                    touches=len(mid_indices),
                    score=base_score,
                    last_swing_idx=last_idx,
                )

    return list(candidates.values())


# ==========================================================
#                   SCORING (BASE, NO DIRECTION)
# ==========================================================
def _calculate_base_zone_score(
    lower: float,
    upper: float,
    height: float,
    touches: int,
    last_idx: int,
    last_bar_idx: int,
    context: AOIContext,
) -> float:
    """
    Base AOI score before trend-direction bias:
      score = density * recency_factor * extremity_factor
    """
    # 1) Touch Density
    density = (touches ** 1.2) / max(height, 1e-6)

    # 2) Recency
    bars_since_last = last_bar_idx - last_idx
    recency_factor = 1 / (1 + (bars_since_last / 100.0))

    # 3) Extremity (bonus near 4H highs/lows)
    zone_mid = (upper + lower) / 2.0
    range_mid = (context.base_high + context.base_low) / 2.0
    range_half = max((context.base_high - context.base_low) / 2.0, 1e-9)
    distance_from_mid = abs(zone_mid - range_mid)
    extremity_factor = 1 + (distance_from_mid / range_half) * 0.2  # up to +20%

    return density * recency_factor * extremity_factor


# ==========================================================
#                   FILTERS & CLEANUP
# ==========================================================
def _has_sufficient_spacing(indices: List[int]) -> bool:
    """Ensure swing touches are spaced out in time."""
    return all(indices[i] - indices[i - 1] >= AOI_MIN_SWING_GAP_BARS for i in range(1, len(indices)))


def _filter_zones_by_bounds(zones: List[AOIZoneCandidate], context: AOIContext) -> List[AOIZoneCandidate]:
    low_allowed = context.base_low - context.tolerance_price
    high_allowed = context.base_high + context.tolerance_price
    return [
        z for z in zones
        if low_allowed <= z.lower_bound <= high_allowed
        and low_allowed <= z.upper_bound <= high_allowed
        and z.height <= context.max_height_price
    ]


def _merge_nearby_zones(zones: List[AOIZoneCandidate], context: AOIContext) -> List[AOIZoneCandidate]:
    """Merge nearby zones if union stays under height cap; keep stronger score/last touch."""
    if not zones:
        return []
    zones = sorted(zones, key=lambda z: z.lower_bound)
    merged: List[AOIZoneCandidate] = [zones[0]]
    tol = pips_to_price(AOI_OVERLAP_TOLERANCE_PIPS, context.pip_size)

    for zone in zones[1:]:
        last = merged[-1]
        if zone.lower_bound <= last.upper_bound + tol:
            new_lower = min(last.lower_bound, zone.lower_bound)
            new_upper = max(last.upper_bound, zone.upper_bound)
            new_height = new_upper - new_lower
            if new_height <= context.max_height_price:
                merged[-1] = AOIZoneCandidate(
                    lower_bound=new_lower,
                    upper_bound=new_upper,
                    height=new_height,
                    touches=last.touches + zone.touches,
                    score=max(last.score, zone.score),
                    last_swing_idx=max(last.last_swing_idx, zone.last_swing_idx),
                )
            else:
                merged.append(zone)
        else:
            merged.append(zone)
    return merged


def _filter_old_zones_by_bars(zones: List[AOIZoneCandidate], last_bar_idx: int) -> List[AOIZoneCandidate]:
    cutoff = last_bar_idx - AOI_MAX_AGE_BARS
    return [z for z in zones if z.last_swing_idx >= cutoff]


def _filter_overlapping_zones(zones: List[AOIZoneCandidate], context: AOIContext) -> List[AOIZoneCandidate]:
    """Keep strongest AOIs and remove overlapping/near-duplicate ones."""
    if not zones:
        return []
    tol = pips_to_price(AOI_OVERLAP_TOLERANCE_PIPS, context.pip_size)
    zones = sorted(zones, key=lambda z: z.score, reverse=True)

    selected: List[AOIZoneCandidate] = []
    for z in zones:
        overlap = any(
            not (z.upper_bound < ex.lower_bound - tol or z.lower_bound > ex.upper_bound + tol)
            for ex in selected
        )
        if not overlap:
            selected.append(z)
    return sorted(selected, key=lambda z: z.lower_bound)


# ==========================================================
#          DIRECTIONAL WEIGHTING & CLASSIFICATION
# ==========================================================
def _apply_directional_weighting_and_classify(
    zones: List[Dict[str, float]],
    current_price: float,
    last_bar_idx: int,
    trend_direction: str,
    context: AOIContext,
) -> List[Dict[str, float]]:
    """
    Apply direction-aware weighting to base score:
      - Bearish → AOIs ABOVE price are 'tradable' (sell), BELOW are 'reference'
      - Bullish → AOIs BELOW price are 'tradable' (buy), ABOVE are 'reference'
    Label each AOI with 'type' and return list with updated scores.
    """
    out: List[Dict[str, float]] = []
    for z in zones:
        lower, upper = z["lower_bound"], z["upper_bound"]
        zone_above_price = lower > current_price
        zone_below_price = upper < current_price

        # Determine if zone is on the tradable side
        if trend_direction == "bearish":
            is_tradable = zone_above_price
        elif trend_direction == "bullish":
            is_tradable = zone_below_price
        else:
            is_tradable = False

        # Apply alignment weighting to score
        weighted_score = z["score"] * (AOI_ALIGNMENT_WEIGHT if is_tradable else 1.0)

        out.append({
            "lower_bound": float(lower),
            "upper_bound": float(upper),
            "score": float(weighted_score),
            "touches": int(z["touches"]),
            "last_swing_idx": int(z["last_swing_idx"]),
            "type": "tradable" if is_tradable else "reference",
        })
    return out


# ==========================================================
#                      VALIDATION
# ==========================================================
def _is_zone_within_extended_bounds(lower: float, upper: float, context: AOIContext) -> bool:
    """Check if potential AOI lies within (or slightly beyond) 4H range via tolerance."""
    return (context.base_low - context.tolerance_price) <= lower and upper <= (context.base_high + context.tolerance_price)


# ==========================================================
#                TREND PROVIDER (PLUGGABLE)
# ==========================================================
def _determine_trend(symbol: str, timeframe: str) -> Optional[str]:
    return db_handler.fetch_trend_bias(symbol, timeframe)[0]  # expected: 'bullish'/'bearish'/'neutral'/None


