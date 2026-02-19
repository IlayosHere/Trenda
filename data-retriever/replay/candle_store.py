"""Candle store for preloading and memory-based access.

Fetches all required candles once before replay loop begins,
providing efficient time-based slicing and index-based access
with no API calls during replay iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import TIMEFRAME_HOURS

import pandas as pd

from .config import (
    OUTCOME_WINDOW_BARS,
    TIMEFRAME_1H,
    TIMEFRAME_4H,
    TIMEFRAME_1D,
    TIMEFRAME_1W,
    MT5_INTERVALS,
    CANDLE_FETCH_BUFFER,
    ACTIVE_PROFILE,
)


def get_broker_intervals() -> dict:
    """Get the MT5 interval mapping."""
    return MT5_INTERVALS


@dataclass
class TimeframeCandles:
    """Container for candles of a single timeframe."""
    
    timeframe: str
    candles: pd.DataFrame = field(default_factory=pd.DataFrame)
    
    def __post_init__(self) -> None:
        if not self.candles.empty and "time" in self.candles.columns:
            self.candles = self.candles.sort_values("time").reset_index(drop=True)
    
    @property
    def is_empty(self) -> bool:
        return self.candles.empty
    
    def get_candles_up_to(self, as_of_time: datetime) -> pd.DataFrame:
        """Return only closed candles as of the given time.
        
        For HTF candles, we must filter by CLOSE time, not open time.
        A 4H candle opening at 08:00 closes at 12:00 - it should NOT
        be included if as_of_time is 09:00 (candle not yet closed).
        
        Args:
            as_of_time: The simulation time (usually 1H candle close)
            
        Returns:
            DataFrame of candles that have CLOSED at or before as_of_time
        """
        if self.is_empty:
            return pd.DataFrame()
        
        # Get duration for this timeframe
        duration_hours = TIMEFRAME_HOURS.get(self.timeframe, 1)
        duration = timedelta(hours=duration_hours)
        
        # Filter by close time: candle closes at open_time + duration
        # A candle is closed when open_time + duration <= as_of_time
        close_times = self.candles["time"] + duration
        return self.candles[close_times <= as_of_time].copy()
    
    def get_candle_at_index(self, index: int) -> Optional[pd.Series]:
        """Get candle at specific index (0-based)."""
        if self.is_empty or index < 0 or index >= len(self.candles):
            return None
        return self.candles.iloc[index]
    
    def get_candles_after_index(self, start_index: int, count: int) -> pd.DataFrame:
        """Get `count` candles starting after `start_index` (exclusive)."""
        if self.is_empty:
            return pd.DataFrame()
        start = start_index + 1
        end = start + count
        return self.candles.iloc[start:end].copy()
    
    def find_index_by_time(self, target_time: datetime) -> Optional[int]:
        """Find index of candle with matching time.
        
        Handles timezone normalization - compares UTC values regardless of
        whether inputs are timezone-aware or naive.
        """
        if self.is_empty:
            return None
        
        # Normalize target_time to naive UTC
        if target_time.tzinfo is not None:
            target_utc = target_time.replace(tzinfo=None) if target_time.utcoffset().total_seconds() == 0 else target_time.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            target_utc = target_time
        
        # Check if candle times are timezone-aware
        first_candle_time = self.candles.iloc[0]["time"]
        candle_times_are_tz_aware = hasattr(first_candle_time, 'tzinfo') and first_candle_time.tzinfo is not None
        
        if candle_times_are_tz_aware:
            # Convert candle times to naive UTC for comparison
            candle_times_utc = self.candles["time"].apply(
                lambda t: t.replace(tzinfo=None) if t.utcoffset().total_seconds() == 0 else t.astimezone(timezone.utc).replace(tzinfo=None)
            )
            matches = self.candles[candle_times_utc == target_utc]
        else:
            # Candle times are already naive - compare directly
            matches = self.candles[self.candles["time"] == target_utc]
        
        if matches.empty:
            return None
        return int(matches.index[0])
    
    def get_last_closed_index(self, as_of_time: datetime) -> Optional[int]:
        """Return index of the last fully closed candle as of the given time.
        
        Uses close time (open + duration) to determine if a candle is closed.
        """
        if self.is_empty:
            return None
        
        # Get duration for this timeframe
        duration_hours = TIMEFRAME_HOURS.get(self.timeframe, 1)
        duration = timedelta(hours=duration_hours)
        
        # Filter by close time
        close_times = self.candles["time"] + duration
        closed = self.candles[close_times <= as_of_time]
        if closed.empty:
            return None
        return int(closed.index[-1])
    
    def __len__(self) -> int:
        return len(self.candles)


class CandleStore:
    """In-memory candle store for a single symbol.
    
    Stores candles for timeframes required by the active profile,
    plus 1H candles for outcome computation.
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        # Initialize slots for all required TFs from the active profile
        self._candles: dict[str, TimeframeCandles] = {}
        for tf in ACTIVE_PROFILE.all_required_timeframes:
            self._candles[tf] = TimeframeCandles(tf)
        # Always ensure 1H is available for outcome computation
        if TIMEFRAME_1H not in self._candles:
            self._candles[TIMEFRAME_1H] = TimeframeCandles(TIMEFRAME_1H)
    
    def load_candles(
        self,
        start_date: datetime,
        end_date: datetime,
        fetch_func: callable,
    ) -> None:
        """Load all candles for all required timeframes."""
        profile = ACTIVE_PROFILE
        fetch_end_date = end_date + timedelta(hours=OUTCOME_WINDOW_BARS + CANDLE_FETCH_BUFFER)
        replay_hours = int((end_date - start_date).total_seconds() / 3600) + 1
        
        for tf in self._candles:
            tf_hours = TIMEFRAME_HOURS.get(tf, 1)
            bars_per_replay = int(replay_hours / tf_hours) + 1 if tf_hours > 0 else replay_hours
            
            # Determine the largest lookback needed for this TF across all roles
            max_lookback = CANDLE_FETCH_BUFFER
            # Check if it's a trend TF
            if tf in profile.trend_alignment_tfs:
                max_lookback = max(max_lookback, profile.lookback_for_trend(tf))
            # Check if it's an AOI TF
            if tf in (profile.aoi_tf_low, profile.aoi_tf_high):
                max_lookback = max(max_lookback, profile.lookback_for_aoi(tf))
            # Entry TF needs lookback + outcome window
            if tf == profile.entry_tf:
                max_lookback = max(max_lookback, profile.lookback_entry)
            # 1H always needs outcome window
            if tf == TIMEFRAME_1H:
                max_lookback = max(max_lookback, OUTCOME_WINDOW_BARS)
            
            total_candles = max_lookback + bars_per_replay + CANDLE_FETCH_BUFFER
            self._fetch_and_store(tf, total_candles, fetch_func, fetch_end_date)
    
    def _fetch_and_store(
        self,
        timeframe: str,
        lookback: int,
        fetch_func: callable,
        end_date: datetime,
    ) -> None:
        """Fetch candles for a timeframe and store them."""
        intervals = get_broker_intervals()
        interval = intervals.get(timeframe)
        if interval is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        
        df = fetch_func(self.symbol, interval, lookback, end_date)
        if df is not None and not df.empty:
            self._candles[timeframe] = TimeframeCandles(timeframe, df)
    
    def get(self, timeframe: str) -> TimeframeCandles:
        """Get candles for a specific timeframe."""
        if timeframe not in self._candles:
            raise KeyError(f"Unknown timeframe: {timeframe}")
        return self._candles[timeframe]
    
    def get_1h_candles(self) -> TimeframeCandles:
        """Convenience accessor for 1H candles."""
        return self._candles[TIMEFRAME_1H]
    
    def get_4h_candles(self) -> TimeframeCandles:
        """Convenience accessor for 4H candles."""
        return self._candles[TIMEFRAME_4H]
    
    def get_1d_candles(self) -> TimeframeCandles:
        """Convenience accessor for 1D candles."""
        return self._candles[TIMEFRAME_1D]
    
    def get_1w_candles(self) -> TimeframeCandles:
        """Convenience accessor for 1W candles."""
        return self._candles[TIMEFRAME_1W]
    
    def get_entry_candles(self) -> TimeframeCandles:
        """Get candles for the active profile's entry timeframe."""
        return self._candles[ACTIVE_PROFILE.entry_tf]
    
    def get_replay_1h_indices(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[int]:
        """Get indices of 1H candles within the replay window."""
        candles_1h = self.get_1h_candles()
        if candles_1h.is_empty:
            return []
        df = candles_1h.candles
        mask = (df["time"] >= start_date) & (df["time"] <= end_date)
        return list(df[mask].index)
    
    def get_replay_entry_indices(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[int]:
        """Get indices of entry-TF candles within the replay window."""
        entry_candles = self.get_entry_candles()
        if entry_candles.is_empty:
            return []
        df = entry_candles.candles
        mask = (df["time"] >= start_date) & (df["time"] <= end_date)
        return list(df[mask].index)
    
    def summary(self) -> dict[str, int]:
        """Return count of candles per timeframe."""
        return {tf: len(tc) for tf, tc in self._candles.items()}


def create_candle_fetcher():
    """Create a fetch function using MT5 for historical data.
    
    Returns a function: (symbol, interval, lookback, end_date) -> DataFrame
    """
    from externals.data_fetcher import fetch_data
    
    def fetcher(
        symbol: str,
        interval: str,
        lookback: int,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Fetch historical candles ending at end_date."""
        return fetch_data(
            symbol=symbol,
            timeframe=interval,
            lookback=lookback,
            timeframe_label=None,  # Don't trim - we want all historical data
            closed_candles_only=False,  # We'll filter ourselves during replay
            end_date=end_date,  # Fetch candles ending at this date
        )
    
    return fetcher


def load_symbol_candles(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
) -> CandleStore:
    """Load all candles for a symbol into a CandleStore.
    
    Args:
        symbol: Forex pair symbol (e.g., "EURUSD")
        start_date: Replay start date
        end_date: Replay end date
        
    Returns:
        CandleStore populated with all required candles
    """
    store = CandleStore(symbol)
    fetcher = create_candle_fetcher()
    store.load_candles(start_date, end_date, fetcher)
    return store

