"""AOI-based stop loss distance calculations."""

from dataclasses import dataclass

from models import TrendDirection


# --- SL/TP Model Constants ---
SL_MODEL_VERSION = 'AOI_MAX_ATR_2_5_v1'
TP_MODEL_VERSION = 'TP_SINGLE_2_25R_v1'

# Volatility floor: SL is never less than this many ATR
MIN_SL_ATR = 2.5

# Take profit multiplier (R units)
TP_R_MULTIPLIER = 2.25


@dataclass(frozen=True)
class StopLossData:
    """Computed stop loss and take profit distances."""
    
    # Model versions for tracking
    sl_model_version: str
    tp_model_version: str
    
    # Structural SL (raw distance from entry to AOI edge)
    aoi_structural_sl_distance_price: float
    aoi_structural_sl_distance_atr: float
    
    # Effective SL = max(structural, 2.5 ATR)
    effective_sl_distance_price: float
    effective_sl_distance_atr: float
    
    # Effective TP = 2.25 × effective SL
    effective_tp_distance_price: float
    effective_tp_distance_atr: float
    
    # Trade profile (reserved for future use)
    trade_profile: str | None


def compute_sl_tp_distances(
    direction: TrendDirection,
    entry_price: float,
    aoi_low: float,
    aoi_high: float,
    atr_1h: float,
) -> StopLossData:
    """
    Compute stop loss and take profit distances.
    
    SL Rule (deterministic):
        effective_sl_distance_atr = max(aoi_structural_sl_distance_atr, 2.5)
    
    The structural distance is derived from the AOI edge, and 2.5 ATR is a
    volatility floor that prevents the SL from sitting inside normal
    retracement noise.
    
    TP Rule:
        effective_tp_distance = 2.25 × effective_sl_distance
    
    Args:
        direction: Trade direction (BULLISH/BEARISH)
        entry_price: Entry price of the signal
        aoi_low: Lower bound of the AOI zone
        aoi_high: Upper bound of the AOI zone
        atr_1h: 1H ATR for normalization
        
    Returns:
        StopLossData with all computed distances
    """
    # A) Structural SL distance (price) - distance from entry to AOI edge
    if direction == TrendDirection.BULLISH:
        structural_dist_price = entry_price - aoi_low
    else:
        structural_dist_price = aoi_high - entry_price
    
    # B) Structural SL in ATR units
    structural_dist_atr = structural_dist_price / atr_1h if atr_1h > 0 else 0.0
    
    # C) Effective SL = max(structural, 2.5 ATR)
    effective_sl_atr = max(structural_dist_atr, MIN_SL_ATR)
    effective_sl_price = effective_sl_atr * atr_1h
    
    # D) Effective TP = 2.25 × effective SL
    effective_tp_atr = effective_sl_atr * TP_R_MULTIPLIER
    effective_tp_price = effective_sl_price * TP_R_MULTIPLIER
    
    return StopLossData(
        sl_model_version=SL_MODEL_VERSION,
        tp_model_version=TP_MODEL_VERSION,
        aoi_structural_sl_distance_price=structural_dist_price,
        aoi_structural_sl_distance_atr=structural_dist_atr,
        effective_sl_distance_price=effective_sl_price,
        effective_sl_distance_atr=effective_sl_atr,
        effective_tp_distance_price=effective_tp_price,
        effective_tp_distance_atr=effective_tp_atr,
        trade_profile=None,
    )


# --- Legacy function for backwards compatibility ---
# TODO: Remove after production code is updated

@dataclass(frozen=True)
class AOIStopLossData:
    """DEPRECATED: Use StopLossData instead."""
    
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
    DEPRECATED: Legacy function for backwards compatibility with production code.
    
    This uses the OLD logic (structural + 0.25 ATR tolerance).
    Replay should use compute_sl_tp_distances() instead.
    """
    AOI_SL_TOLERANCE_ATR = 0.25
    
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
