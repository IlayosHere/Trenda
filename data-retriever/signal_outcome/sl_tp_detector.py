"""SL/TP hit detection for outcome computation."""

from dataclasses import dataclass

import pandas as pd

from models import TrendDirection

from .constants import (
    AoiRrOutcome,
    R_MULTIPLIER_1,
    R_MULTIPLIER_1_5,
    R_MULTIPLIER_2,
)


@dataclass(frozen=True)
class RTargets:
    """R-based take profit target prices."""
    
    tp_1: float
    tp_1_5: float
    tp_2: float


@dataclass(frozen=True)
class SlTpHits:
    """Bars to SL/TP hits (None if not hit)."""
    
    bars_to_aoi_sl_hit: int | None
    bars_to_r_1: int | None
    bars_to_r_1_5: int | None
    bars_to_r_2: int | None
    aoi_rr_outcome: str


def compute_sl_tp_hits(
    candles: pd.DataFrame,
    direction: TrendDirection,
    entry_price: float,
    aoi_effective_sl_distance_price: float,
) -> SlTpHits:
    """
    Compute SL/TP hit timing and R:R outcome classification.
    
    Iterates through candles once to detect all SL and TP hits efficiently.
    
    Args:
        candles: DataFrame with 48 candles after signal
        direction: Trade direction
        entry_price: Entry price
        aoi_effective_sl_distance_price: Effective SL distance (R value)
        
    Returns:
        SlTpHits with bars to each event and classification
    """
    is_bullish = direction == TrendDirection.BULLISH
    
    # Compute price levels
    sl_price = _compute_sl_price(entry_price, aoi_effective_sl_distance_price, is_bullish)
    targets = _compute_r_targets(entry_price, aoi_effective_sl_distance_price, is_bullish)
    
    # Detect all hits in a single pass
    hits = _detect_all_hits_single_pass(candles, sl_price, targets, is_bullish)
    
    # Classify outcome based on hit timing
    aoi_rr_outcome = _classify_rr_outcome(
        hits["sl"], hits["r1"], hits["r1_5"], hits["r2"]
    )
    
    return SlTpHits(
        bars_to_aoi_sl_hit=hits["sl"],
        bars_to_r_1=hits["r1"],
        bars_to_r_1_5=hits["r1_5"],
        bars_to_r_2=hits["r2"],
        aoi_rr_outcome=aoi_rr_outcome,
    )


def _compute_sl_price(
    entry_price: float, effective_sl_distance: float, is_bullish: bool
) -> float:
    """Compute the effective stop loss price."""
    if is_bullish:
        return entry_price - effective_sl_distance
    return entry_price + effective_sl_distance


def _compute_r_targets(
    entry_price: float, r_distance: float, is_bullish: bool
) -> RTargets:
    """Compute R-based take profit target prices."""
    if is_bullish:
        tp_1 = entry_price + R_MULTIPLIER_1 * r_distance
        tp_1_5 = entry_price + R_MULTIPLIER_1_5 * r_distance
        tp_2 = entry_price + R_MULTIPLIER_2 * r_distance
    else:
        tp_1 = entry_price - R_MULTIPLIER_1 * r_distance
        tp_1_5 = entry_price - R_MULTIPLIER_1_5 * r_distance
        tp_2 = entry_price - R_MULTIPLIER_2 * r_distance
    
    return RTargets(tp_1=tp_1, tp_1_5=tp_1_5, tp_2=tp_2)


def _detect_all_hits_single_pass(
    candles: pd.DataFrame,
    sl_price: float,
    targets: RTargets,
    is_bullish: bool,
) -> dict[str, int | None]:
    """
    Detect SL and all TP hits in a single pass through candles.
    
    Args:
        candles: DataFrame with candles
        sl_price: Stop loss price level
        targets: R-based take profit targets
        is_bullish: True if bullish trade
        
    Returns:
        Dict with keys 'sl', 'r1', 'r1_5', 'r2' - each is bar number (1-based) or None
    """
    hits = {"sl": None, "r1": None, "r1_5": None, "r2": None}
    
    for bar_num, (_, candle) in enumerate(candles.iterrows(), start=1):
        high = candle["high"]
        low = candle["low"]
        
        # Check each condition only if not already hit
        if hits["sl"] is None and _is_sl_hit(high, low, sl_price, is_bullish):
            hits["sl"] = bar_num
            
        if hits["r1"] is None and _is_tp_hit(high, low, targets.tp_1, is_bullish):
            hits["r1"] = bar_num
            
        if hits["r1_5"] is None and _is_tp_hit(high, low, targets.tp_1_5, is_bullish):
            hits["r1_5"] = bar_num
            
        if hits["r2"] is None and _is_tp_hit(high, low, targets.tp_2, is_bullish):
            hits["r2"] = bar_num
        
        # Early exit if all levels have been hit
        if all(v is not None for v in hits.values()):
            break
    
    return hits


def _is_sl_hit(high: float, low: float, sl_price: float, is_bullish: bool) -> bool:
    """Check if stop loss was hit on this candle."""
    if is_bullish:
        # SL hit when candle.low <= sl_price
        return low <= sl_price
    # SL hit when candle.high >= sl_price
    return high >= sl_price


def _is_tp_hit(high: float, low: float, tp_price: float, is_bullish: bool) -> bool:
    """Check if take profit was hit on this candle."""
    if is_bullish:
        # TP hit when candle.high >= tp_price
        return high >= tp_price
    # TP hit when candle.low <= tp_price
    return low <= tp_price


def _classify_rr_outcome(
    sl_bar: int | None,
    r1_bar: int | None,
    r1_5_bar: int | None,
    r2_bar: int | None,
) -> str:
    """
    Determine the R:R outcome classification.
    
    Priority order ensures highest R wins, SL only wins if it truly came first.
    """
    # If all values are None
    if sl_bar is None and r1_bar is None and r1_5_bar is None and r2_bar is None:
        return AoiRrOutcome.NONE.value
    
    # If SL hit and it came before all R hits
    if sl_bar is not None:
        r_bars = [r1_bar, r1_5_bar, r2_bar]
        sl_came_first = all(
            r_bar is None or sl_bar < r_bar for r_bar in r_bars
        )
        if sl_came_first:
            return AoiRrOutcome.SL_BEFORE_ANY_TP.value
    
    # Check R hits in descending order (highest R wins)
    if r2_bar is not None and (sl_bar is None or r2_bar < sl_bar):
        return AoiRrOutcome.TP2_BEFORE_SL.value
    
    if r1_5_bar is not None and (sl_bar is None or r1_5_bar < sl_bar):
        return AoiRrOutcome.TP1_5_BEFORE_SL.value
    
    if r1_bar is not None and (sl_bar is None or r1_bar < sl_bar):
        return AoiRrOutcome.TP1_BEFORE_SL.value
    
    return AoiRrOutcome.NONE.value
