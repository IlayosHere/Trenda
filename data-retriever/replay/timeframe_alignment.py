"""Timeframe alignment helpers to prevent lookahead bias.

Provides utilities to determine which higher-timeframe candles are
available at any given 1H candle close time, ensuring all state
calculations use only data that would have been known at that moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .candle_store import CandleStore
from .config import (
    TIMEFRAME_4H,
    TIMEFRAME_1D,
    TIMEFRAME_1W,
)


@dataclass
class TimeframeCloseState:
    """Tracks the last closed candle index for each higher timeframe."""
    
    idx_4h: Optional[int] = None
    idx_1d: Optional[int] = None
    idx_1w: Optional[int] = None


@dataclass
class NewCloseFlags:
    """Flags indicating which timeframes have new closed candles."""
    
    new_4h: bool = False
    new_1d: bool = False
    new_1w: bool = False
    
    def any_new(self) -> bool:
        """Return True if any higher timeframe has a new close."""
        return self.new_4h or self.new_1d or self.new_1w


class TimeframeAligner:
    """Manages timeframe alignment for replay iteration.
    
    At each 1H candle close, determines:
    1. Which higher-timeframe candles are closed (available for use)
    2. Whether any higher timeframe has a NEW close since last check
    
    This ensures trend/AOI calculations only use data available at each moment.
    """
    
    def __init__(self, candle_store: CandleStore):
        self._store = candle_store
        self._prev_state = TimeframeCloseState()
        self._current_state = TimeframeCloseState()
    
    def get_last_closed_index(self, timeframe: str, as_of_time: datetime) -> Optional[int]:
        """Return index of last closed candle for a timeframe.
        
        Args:
            timeframe: One of 4H, 1D, 1W
            as_of_time: The current simulation time (1H candle close time)
            
        Returns:
            Index of the last candle that closed at or before as_of_time,
            or None if no candles are available.
        """
        candles = self._store.get(timeframe)
        return candles.get_last_closed_index(as_of_time)
    
    def detect_new_closes(self, as_of_time: datetime) -> NewCloseFlags:
        """Detect which higher timeframes have NEW closes at this time.
        
        Compares current closed indices against previous check to
        determine if a new candle has closed for each higher timeframe.
        
        Args:
            as_of_time: Current simulation time (1H candle close time)
            
        Returns:
            NewCloseFlags with True for each TF that has a new close
        """
        # Get current closed indices for each higher timeframe
        idx_4h = self.get_last_closed_index(TIMEFRAME_4H, as_of_time)
        idx_1d = self.get_last_closed_index(TIMEFRAME_1D, as_of_time)
        idx_1w = self.get_last_closed_index(TIMEFRAME_1W, as_of_time)
        
        # Compare against previous state
        flags = NewCloseFlags(
            new_4h=self._is_new_close(idx_4h, self._prev_state.idx_4h),
            new_1d=self._is_new_close(idx_1d, self._prev_state.idx_1d),
            new_1w=self._is_new_close(idx_1w, self._prev_state.idx_1w),
        )
        
        # Update state for next iteration
        self._prev_state = TimeframeCloseState(
            idx_4h=idx_4h,
            idx_1d=idx_1d,
            idx_1w=idx_1w,
        )
        self._current_state = self._prev_state
        
        return flags
    
    def get_current_state(self) -> TimeframeCloseState:
        """Return the current timeframe close state."""
        return self._current_state
    
    def _is_new_close(
        self,
        current_idx: Optional[int],
        prev_idx: Optional[int],
    ) -> bool:
        """Check if a new candle has closed."""
        if current_idx is None:
            return False
        if prev_idx is None:
            # First iteration - treat as new close to trigger initial state
            return True
        return current_idx > prev_idx
    
    def reset(self) -> None:
        """Reset aligner state for a new replay run."""
        self._prev_state = TimeframeCloseState()
        self._current_state = TimeframeCloseState()


def is_4h_boundary(dt: datetime) -> bool:
    """Check if datetime is a 4H candle boundary.
    
    4H candles close at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.
    """
    return dt.hour % 4 == 0 and dt.minute == 0


def is_1d_boundary(dt: datetime) -> bool:
    """Check if datetime is a 1D candle boundary.
    
    Daily candles typically close at 00:00 UTC (midnight).
    Note: Some brokers use different daily close times.
    """
    return dt.hour == 0 and dt.minute == 0


def is_1w_boundary(dt: datetime) -> bool:
    """Check if datetime is a 1W candle boundary.
    
    Weekly candles typically close on Sunday/Monday midnight.
    weekday() returns 0=Monday, 6=Sunday.
    
    Forex weekly close is typically Sunday 21:00 UTC / Monday 00:00 UTC.
    Using Monday 00:00 as the boundary.
    """
    return dt.weekday() == 0 and dt.hour == 0 and dt.minute == 0


def get_candles_for_analysis(
    candle_store: CandleStore,
    timeframe: str,
    as_of_time: datetime,
    lookback: int,
) -> Optional[list]:
    """Get candles for trend/AOI analysis at a specific point in time.
    
    Args:
        candle_store: The candle store for the symbol
        timeframe: Timeframe to get candles for
        as_of_time: Current simulation time
        lookback: Number of candles to include
        
    Returns:
        DataFrame of the last `lookback` candles closed at or before as_of_time
    """
    tf_candles = candle_store.get(timeframe)
    available = tf_candles.get_candles_up_to(as_of_time)
    
    if available.empty:
        return None
    
    # Return only the last `lookback` candles
    return available.tail(lookback)
