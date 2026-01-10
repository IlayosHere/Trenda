"""Real-time HTF context calculator for production signal detection.

Computes HTF range positions and obstacle distances at signal time.
Uses last candle high/low from MT5 (same as replay approach).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5

from models import TrendDirection
from entry.gates.config import HTF_TIMEFRAMES, RANGE_POSITION_TIMEFRAMES, NO_OBSTACLE_DISTANCE_ATR


# MT5 timeframe mapping
TF_TO_MT5 = {
    "4H": mt5.TIMEFRAME_H4,
    "1D": mt5.TIMEFRAME_D1,
    "1W": mt5.TIMEFRAME_W1,
}


@dataclass
class TimeframeLevels:
    """High/low levels for a single timeframe."""
    timeframe: str
    high: Optional[float] = None
    low: Optional[float] = None


@dataclass
class HTFContext:
    """HTF context data computed at signal time."""
    # HTF range positions (0-1)
    htf_range_position_daily: Optional[float] = None
    htf_range_position_weekly: Optional[float] = None
    
    # Distance to next obstacle in ATR units
    distance_to_next_htf_obstacle_atr: Optional[float] = None
    
    # All timeframe levels
    levels: Dict[str, TimeframeLevels] = field(default_factory=dict)
    
    @property
    def daily_high(self) -> Optional[float]:
        return self.levels.get("1D", TimeframeLevels("1D")).high
    
    @property
    def daily_low(self) -> Optional[float]:
        return self.levels.get("1D", TimeframeLevels("1D")).low
    
    @property
    def weekly_high(self) -> Optional[float]:
        return self.levels.get("1W", TimeframeLevels("1W")).high
    
    @property
    def weekly_low(self) -> Optional[float]:
        return self.levels.get("1W", TimeframeLevels("1W")).low
    
    @property
    def h4_high(self) -> Optional[float]:
        return self.levels.get("4H", TimeframeLevels("4H")).high
    
    @property
    def h4_low(self) -> Optional[float]:
        return self.levels.get("4H", TimeframeLevels("4H")).low


def _fetch_all_htf_levels(symbol: str, timeframes: Tuple[str, ...]) -> Dict[str, TimeframeLevels]:
    """Fetch high/low levels from last closed candle for all timeframes.
    
    Uses MT5 to get the most recent candle's high/low (same approach as replay).
    """
    levels = {}
    for tf in timeframes:
        tf_mt5 = TF_TO_MT5.get(tf)
        if tf_mt5 is None:
            levels[tf] = TimeframeLevels(timeframe=tf)
            continue
        
        # Fetch last 2 candles (current may be incomplete, use previous)
        rates = mt5.copy_rates_from_pos(symbol, tf_mt5, 0, 2)
        
        if rates is not None and len(rates) >= 2:
            # Use the second-to-last candle (last completed candle)
            last_candle = rates[-2]
            levels[tf] = TimeframeLevels(
                timeframe=tf,
                high=float(last_candle["high"]),
                low=float(last_candle["low"]),
            )
        elif rates is not None and len(rates) == 1:
            # Only one candle available, use it
            last_candle = rates[0]
            levels[tf] = TimeframeLevels(
                timeframe=tf,
                high=float(last_candle["high"]),
                low=float(last_candle["low"]),
            )
        else:
            levels[tf] = TimeframeLevels(timeframe=tf)
    
    return levels


def _compute_range_position(
    price: float,
    range_low: Optional[float],
    range_high: Optional[float],
) -> Optional[float]:
    """Compute position within a range (0 = at low, 1 = at high)."""
    if range_low is None or range_high is None:
        return None
    
    range_size = range_high - range_low
    if range_size <= 0:
        return None
    
    position = (price - range_low) / range_size
    return max(0.0, min(1.0, position))  # Clamp to 0-1


def _get_obstacles_for_direction(
    levels: Dict[str, TimeframeLevels],
    entry_price: float,
    is_bullish: bool,
) -> List[float]:
    """Get relevant obstacles based on trade direction."""
    obstacles = []
    
    for tf_levels in levels.values():
        if is_bullish:
            # Looking for resistance (highs above entry)
            if tf_levels.high is not None and tf_levels.high > entry_price:
                obstacles.append(tf_levels.high)
        else:
            # Looking for support (lows below entry)
            if tf_levels.low is not None and tf_levels.low < entry_price:
                obstacles.append(tf_levels.low)
    
    return obstacles


def _compute_obstacle_distance(
    entry_price: float,
    atr_1h: float,
    is_bullish: bool,
    obstacles: List[float],
) -> Optional[float]:
    """Compute distance to nearest obstacle in ATR units."""
    if atr_1h <= 0:
        return None
    
    if not obstacles:
        return NO_OBSTACLE_DISTANCE_ATR
    
    if is_bullish:
        nearest = min(obstacles)  # Closest resistance above
        distance = nearest - entry_price
    else:
        nearest = max(obstacles)  # Closest support below
        distance = entry_price - nearest
    
    return distance / atr_1h


def compute_htf_context(
    symbol: str,
    entry_price: float,
    atr_1h: float,
    direction: TrendDirection,
) -> HTFContext:
    """
    Compute HTF context at signal time.
    
    Uses last candle high/low from MT5 (same approach as replay).
    
    Args:
        symbol: Trading symbol
        entry_price: Entry price of the signal
        atr_1h: 1H ATR for normalization
        direction: Trade direction
        
    Returns:
        HTFContext with range positions and obstacle distances
    """
    # Fetch all HTF levels from last candles (via MT5)
    levels = _fetch_all_htf_levels(symbol, HTF_TIMEFRAMES)
    
    # Compute range positions for configured timeframes
    range_positions = {}
    for tf in RANGE_POSITION_TIMEFRAMES:
        tf_levels = levels.get(tf)
        if tf_levels:
            range_positions[tf] = _compute_range_position(
                entry_price, tf_levels.low, tf_levels.high
            )
    
    # Compute obstacle distance
    is_bullish = direction == TrendDirection.BULLISH
    obstacles = _get_obstacles_for_direction(levels, entry_price, is_bullish)
    obstacle_distance = _compute_obstacle_distance(entry_price, atr_1h, is_bullish, obstacles)
    
    return HTFContext(
        htf_range_position_daily=range_positions.get("1D"),
        htf_range_position_weekly=range_positions.get("1W"),
        distance_to_next_htf_obstacle_atr=obstacle_distance,
        levels=levels,
    )


def get_conflicted_timeframe(
    trend_4h: Optional[str],
    trend_1d: Optional[str],
    trend_1w: Optional[str],
    direction: TrendDirection,
) -> Optional[str]:
    """
    Determine which timeframe conflicts with the trade direction.
    
    Returns:
        None if all 3 TFs aligned, otherwise the conflicting TF label
    """
    direction_str = direction.value
    
    # Build alignment map
    alignments = {
        "4H": trend_4h == direction_str if trend_4h else False,
        "1D": trend_1d == direction_str if trend_1d else False,
        "1W": trend_1w == direction_str if trend_1w else False,
    }
    
    # If all aligned, no conflict
    if all(alignments.values()):
        return None
    
    # Find non-aligned timeframes
    non_aligned = [tf for tf, aligned in alignments.items() if not aligned]
    
    # If exactly one is non-aligned, return it
    if len(non_aligned) == 1:
        return non_aligned[0]
    
    # Multiple conflicts - return first non-aligned in priority order
    for tf in ("4H", "1D", "1W"):
        if not alignments[tf]:
            return tf
    
    return None
