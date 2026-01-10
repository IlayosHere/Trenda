"""Candle store for preloading and memory-based access.

Fetches all required candles once before replay loop begins,
providing efficient time-based slicing and index-based access
with no API calls during replay iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from .config import (
    LOOKBACK_1H,
    LOOKBACK_4H,
    LOOKBACK_1D,
    LOOKBACK_1W,
    LOOKBACK_AOI_4H,
    LOOKBACK_AOI_1D,
    OUTCOME_WINDOW_BARS,
    TIMEFRAME_1H,
    TIMEFRAME_4H,
    TIMEFRAME_1D,
    TIMEFRAME_1W,
    MT5_INTERVALS,
    CANDLE_FETCH_BUFFER,
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
        """Return candles where time <= as_of_time (closed candles only)."""
        if self.is_empty:
            return pd.DataFrame()
        return self.candles[self.candles["time"] <= as_of_time].copy()
    
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
        """Return index of the last candle where time <= as_of_time."""
        if self.is_empty:
            return None
        closed = self.candles[self.candles["time"] <= as_of_time]
        if closed.empty:
            return None
        return int(closed.index[-1])
    
    def __len__(self) -> int:
        return len(self.candles)


class CandleStore:
    """In-memory candle store for a single symbol.
    
    Stores candles for all timeframes (1H, 4H, 1D, 1W) and provides
    efficient access methods for replay iteration.
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._candles: dict[str, TimeframeCandles] = {
            TIMEFRAME_1H: TimeframeCandles(TIMEFRAME_1H),
            TIMEFRAME_4H: TimeframeCandles(TIMEFRAME_4H),
            TIMEFRAME_1D: TimeframeCandles(TIMEFRAME_1D),
            TIMEFRAME_1W: TimeframeCandles(TIMEFRAME_1W),
        }
    
    def load_candles(
        self,
        start_date: datetime,
        end_date: datetime,
        fetch_func: callable,
    ) -> None:
        """Load all candles for all timeframes.
        
        Args:
            start_date: Replay start date
            end_date: Replay end date
            fetch_func: Function to fetch candles: (symbol, interval, lookback, end_date) -> DataFrame
        """
        # Calculate the end date for fetching (end_date + outcome window for 1H)
        # Add extra buffer to ensure we have enough candles for outcome computation
        fetch_end_date = end_date + timedelta(hours=OUTCOME_WINDOW_BARS + CANDLE_FETCH_BUFFER)
        
        # Calculate required lookbacks for each timeframe
        # 1H: needs lookback + outcome window + buffer
        
        # Calculate total hours in replay window
        #TODO: change it
        replay_hours = int((end_date - start_date).total_seconds() / 3600) + 1
        total_1h_candles = replay_hours + OUTCOME_WINDOW_BARS
        
        # Fetch 1H candles with end_date
        self._fetch_and_store(TIMEFRAME_1H, total_1h_candles, fetch_func, fetch_end_date)
        
        # Fetch 4H candles
        lookback_4h = max(LOOKBACK_4H, LOOKBACK_AOI_4H) + CANDLE_FETCH_BUFFER
        total_4h_candles = lookback_4h + (replay_hours // 4) + 20
        self._fetch_and_store(TIMEFRAME_4H, total_4h_candles, fetch_func, fetch_end_date)
        
        # Fetch 1D candles
        lookback_1d = max(LOOKBACK_1D, LOOKBACK_AOI_1D) + CANDLE_FETCH_BUFFER
        total_1d_candles = lookback_1d + (replay_hours // 24) + 10
        self._fetch_and_store(TIMEFRAME_1D, total_1d_candles, fetch_func, fetch_end_date)
        
        # Fetch 1W candles
        lookback_1w = LOOKBACK_1W + CANDLE_FETCH_BUFFER
        total_1w_candles = lookback_1w + (replay_hours // 168) + 5
        self._fetch_and_store(TIMEFRAME_1W, total_1w_candles, fetch_func, fetch_end_date)
    
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
    
    def get_replay_1h_indices(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[int]:
        """Get indices of 1H candles within the replay window.
        
        Returns list of indices for candles where:
        start_date <= candle.time <= end_date
        """
        candles_1h = self.get_1h_candles()
        if candles_1h.is_empty:
            return []
        
        df = candles_1h.candles
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

