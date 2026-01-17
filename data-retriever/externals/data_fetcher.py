"""MT5 data fetcher for candle data.

Fetches OHLC data from MetaTrader5 with proper timezone handling,
including DST-aware offset calculation for historical data.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from constants import DATA_ERROR_MSG
from utils.candles import last_expected_close_time, trim_to_closed_candles
from logger import get_logger

logger = get_logger(__name__)

# Lock to serialize MT5 API calls (MT5 is not thread-safe)
_mt5_lock = threading.Lock()

# Import MT5
import MetaTrader5 as mt5


def fetch_data(
    symbol: str,
    timeframe: int | str,
    lookback: int,
    *,
    timeframe_label: str | None = None,
    now: datetime | None = None,
    closed_candles_only: bool = True,
    end_date: datetime | None = None,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLC data from MT5, returning a dataframe of candles.

    When ``timeframe_label`` is provided, any candles whose timestamps extend
    beyond the last expected close for that timeframe are dropped to ensure only
    closed candles are returned.
    
    Args:
        symbol: Forex pair symbol (e.g., "EURUSD")
        timeframe: MT5 timeframe constant (e.g., 16385 for H1)
        lookback: Number of candles to fetch
        timeframe_label: Optional label for closed candle trimming
        now: Optional reference time for closed candle calculation
        closed_candles_only: If True, only return closed candles
        end_date: If provided, fetches `lookback` candles ending at this date.
                  Used for historical/replay data fetching.
    """
    df = _fetch_from_mt5(symbol, timeframe, lookback, end_date=end_date)

    if df is None or timeframe_label is None:
        return df

    if closed_candles_only:
        cutoff_time = last_expected_close_time(
            timeframe_label, now=now or datetime.now(timezone.utc)
        )
        trimmed = trim_to_closed_candles(df, timeframe_label, now=cutoff_time)
        return trimmed

    return df


def _fetch_from_mt5(
    symbol: str,
    timeframe_mt5: int | str,
    lookback: int,
    *,
    end_date: datetime | None = None,
) -> Optional[pd.DataFrame]:
    """Fetch candles from MT5.
    
    Args:
        symbol: Forex pair symbol
        timeframe_mt5: MT5 timeframe constant
        lookback: Number of candles to fetch
        end_date: If provided, fetches candles ending at this date using
                  copy_rates_range. Otherwise uses current position.
    
    Note: Uses a lock to serialize MT5 API calls (MT5 is not thread-safe).
    
    Timezone Handling:
        MT5 timestamps are in broker local time (EET/EEST), not UTC.
        For live data: Uses current time's offset (all candles are recent).
        For historical data: Calculates per-candle offset to handle DST correctly.
    """
    if mt5 is None:
        logger.error("MetaTrader5 is not available in this environment.")
        return None

    tf_int = int(timeframe_mt5)
    is_historical = end_date is not None
    
    # Serialize MT5 API access with lock
    with _mt5_lock:
        if is_historical:
            # Historical data fetch using copy_rates_range
            # Convert to naive datetime for MT5 (it expects local time or naive UTC)
            if end_date.tzinfo is not None:
                end_date_naive = end_date.replace(tzinfo=None)
            else:
                end_date_naive = end_date
            
            # Estimate start_date (overfetch to ensure we get enough candles)
            # Account for weekends and holidays by adding extra buffer
            if tf_int == 16385:  # H1
                hours_back = lookback + 168  # Extra week buffer for gaps
                start_date = end_date_naive - timedelta(hours=hours_back)
            elif tf_int == 16388:  # H4
                hours_back = (lookback + 50) * 4
                start_date = end_date_naive - timedelta(hours=hours_back)
            elif tf_int == 16408:  # D1
                days_back = lookback + 30  # Extra month buffer
                start_date = end_date_naive - timedelta(days=days_back)
            elif tf_int == 32769:  # W1
                days_back = (lookback + 10) * 7
                start_date = end_date_naive - timedelta(days=days_back)
            else:
                # Fallback
                start_date = end_date_naive - timedelta(hours=lookback * 4)
            
            rates = mt5.copy_rates_range(symbol, tf_int, start_date, end_date_naive)
            
            # Check for MT5 errors
            if rates is None or len(rates) == 0:
                error = mt5.last_error()
                if error[0] != 1:  # 1 = success
                    logger.warning(f"MT5 error for {symbol} TF {tf_int}: code={error[0]}, msg={error[1]}")
        else:
            # Live data fetch using current position
            rates = mt5.copy_rates_from_pos(symbol, tf_int, 0, lookback)

        if rates is None or len(rates) == 0:
            logger.error("%s for %s on TF %s", DATA_ERROR_MSG, symbol, timeframe_mt5)
            return None

    # DataFrame processing outside the lock
    df = pd.DataFrame(rates)
    
    # MT5 timestamps are in BROKER LOCAL TIME (EET/EEST, UTC+2/+3)
    # but encoded as Unix timestamps without proper UTC conversion.
    # We need to subtract the broker's UTC offset to get true UTC times.
    
    if is_historical:
        # For historical data, calculate offset PER CANDLE to handle DST boundaries
        # This ensures candles from summer (UTC+3) and winter (UTC+2) are both correct
        df["time"] = df["time"].apply(_convert_mt5_timestamp_to_utc)
    else:
        # For live data, all candles are recent - use single current offset
        from configuration.broker_config import get_broker_utc_offset
        current_offset = get_broker_utc_offset()
        broker_offset_seconds = current_offset * 3600
        df["time"] = pd.to_datetime(df["time"] - broker_offset_seconds, unit="s", utc=True)
    
    # If we used date range, trim to requested lookback
    if is_historical and len(df) > lookback:
        df = df.tail(lookback)
    
    return df


def _convert_mt5_timestamp_to_utc(mt5_timestamp: int) -> datetime:
    """Convert MT5 timestamp to proper UTC datetime.
    
    MT5 timestamps are Unix timestamps but in BROKER LOCAL TIME (not UTC).
    This function:
    1. Interprets the timestamp as if it were UTC
    2. Determines what the broker offset was at that time (handles DST)
    3. Subtracts the offset to get true UTC
    """
    # First, interpret as naive datetime (as if UTC)
    naive_dt = datetime.utcfromtimestamp(mt5_timestamp)
    
    # Create a UTC datetime to pass to offset calculator
    assumed_utc = naive_dt.replace(tzinfo=timezone.utc)
    
    # Get the broker offset that was in effect at this timestamp
    # This correctly handles DST transitions
    from configuration.broker_config import get_broker_utc_offset
    offset_hours = get_broker_utc_offset(assumed_utc)
    
    # Subtract the offset to get true UTC
    true_utc = assumed_utc - timedelta(hours=offset_hours)
    
    return true_utc
