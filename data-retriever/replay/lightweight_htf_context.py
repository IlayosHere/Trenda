"""Lightweight HTF context for replay gate checks.

Only computes the minimal fields needed for gates:
- htf_range_position_mid
- htf_range_position_high
- distance_to_next_htf_obstacle_atr
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from models import TrendDirection
from .config import ACTIVE_PROFILE

if TYPE_CHECKING:
    from .candle_store import CandleStore


@dataclass
class LightweightHTFContext:
    """Minimal HTF context for gate checks only."""
    htf_range_position_mid: Optional[float] = None
    htf_range_position_high: Optional[float] = None
    distance_to_next_htf_obstacle_atr: Optional[float] = None


def compute_lightweight_htf_context(
    candle_store: "CandleStore",
    signal_time: datetime,
    entry_price: float,
    atr_1h: float,
    direction: TrendDirection,
) -> Optional[LightweightHTFContext]:
    """Compute minimal HTF context for gate checks."""
    if atr_1h <= 0:
        return None
    
    is_long = direction == TrendDirection.BULLISH
    result = LightweightHTFContext()
    
    # Get last closed mid-TF candle for range position
    daily_candles = candle_store.get(ACTIVE_PROFILE.trend_tf_mid).get_candles_up_to(signal_time)
    daily_high = None
    daily_low = None
    if daily_candles is not None and len(daily_candles) > 0:
        last_daily = daily_candles.iloc[-1]
        daily_high = float(last_daily["high"])
        daily_low = float(last_daily["low"])
        daily_range = daily_high - daily_low
        if daily_range > 0:
            result.htf_range_position_mid = (entry_price - daily_low) / daily_range
    
    # Get last closed high-TF candle for range position
    weekly_candles = candle_store.get(ACTIVE_PROFILE.trend_tf_high).get_candles_up_to(signal_time)
    weekly_high = None
    weekly_low = None
    if weekly_candles is not None and len(weekly_candles) > 0:
        last_weekly = weekly_candles.iloc[-1]
        weekly_high = float(last_weekly["high"])
        weekly_low = float(last_weekly["low"])
        weekly_range = weekly_high - weekly_low
        if weekly_range > 0:
            result.htf_range_position_high = (entry_price - weekly_low) / weekly_range
    
    # Compute distance to next HTF obstacle
    # Get low-TF levels as well
    candles_4h = candle_store.get(ACTIVE_PROFILE.trend_tf_low).get_candles_up_to(signal_time)
    h4_high = None
    h4_low = None
    if candles_4h is not None and len(candles_4h) > 0:
        last_4h = candles_4h.iloc[-1]
        h4_high = float(last_4h["high"])
        h4_low = float(last_4h["low"])
    
    # Collect obstacles based on direction
    obstacles = []
    if is_long:
        # Looking for resistance (highs above entry)
        if h4_high is not None and h4_high > entry_price:
            obstacles.append((h4_high - entry_price) / atr_1h)
        if daily_high is not None and daily_high > entry_price:
            obstacles.append((daily_high - entry_price) / atr_1h)
        if weekly_high is not None and weekly_high > entry_price:
            obstacles.append((weekly_high - entry_price) / atr_1h)
    else:
        # Looking for support (lows below entry)
        if h4_low is not None and h4_low < entry_price:
            obstacles.append((entry_price - h4_low) / atr_1h)
        if daily_low is not None and daily_low < entry_price:
            obstacles.append((entry_price - daily_low) / atr_1h)
        if weekly_low is not None and weekly_low < entry_price:
            obstacles.append((entry_price - weekly_low) / atr_1h)
    
    if obstacles:
        result.distance_to_next_htf_obstacle_atr = min(obstacles)
    else:
        result.distance_to_next_htf_obstacle_atr = 10.0  # No obstacles = large distance
    
    return result
