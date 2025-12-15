"""AOI-based stop loss distance calculations."""

from dataclasses import dataclass

from models import TrendDirection
from signal_outcome.constants import AOI_SL_TOLERANCE_ATR


@dataclass(frozen=True)
class AOIStopLossData:
    """Computed AOI-based stop loss distances."""
    
    aoi_sl_tolerance_atr: float
    aoi_raw_sl_distance_price: float
    aoi_raw_sl_distance_atr: float
    aoi_effective_sl_distance_price: float
    aoi_effective_sl_distance_atr: float


def compute_aoi_sl_distances(
    direction: TrendDirection,
    entry_price: float,
    aoi_low: float,
    aoi_high: float,
    atr_1h: float,
) -> AOIStopLossData:
    """
    Compute AOI-based stop loss distances.
    
    Args:
        direction: Trade direction (BULLISH/BEARISH)
        entry_price: Entry price of the signal
        aoi_low: Lower bound of the AOI zone
        aoi_high: Upper bound of the AOI zone
        atr_1h: 1H ATR for normalization
        
    Returns:
        AOIStopLossData with all computed distances
    """
    # A) Raw AOI stop distance (price)
    if direction == TrendDirection.BULLISH:
        raw_dist = entry_price - aoi_low
    else:
        raw_dist = aoi_high - entry_price
    
    # B) AOI tolerance (price)
    tolerance_price = atr_1h * AOI_SL_TOLERANCE_ATR
    
    # C) Effective SL distance (price)
    effective_dist = raw_dist + tolerance_price
    
    # D) Normalize distances (ATR units)
    raw_dist_atr = raw_dist / atr_1h if atr_1h > 0 else 0.0
    effective_dist_atr = effective_dist / atr_1h if atr_1h > 0 else 0.0
    
    return AOIStopLossData(
        aoi_sl_tolerance_atr=AOI_SL_TOLERANCE_ATR,
        aoi_raw_sl_distance_price=raw_dist,
        aoi_raw_sl_distance_atr=raw_dist_atr,
        aoi_effective_sl_distance_price=effective_dist,
        aoi_effective_sl_distance_atr=effective_dist_atr,
    )
