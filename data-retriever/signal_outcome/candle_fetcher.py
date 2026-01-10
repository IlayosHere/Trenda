"""Fetches future candles for outcome computation."""

from datetime import datetime, timezone

import pandas as pd

from logger import get_logger

logger = get_logger(__name__)
from configuration.forex_config import TIMEFRAMES
from externals.data_fetcher import fetch_data

from .constants import CANDLE_FETCH_BUFFER, OUTCOME_WINDOW_BARS, TIMEFRAME_1H


def fetch_candles_after_signal(
    symbol: str, signal_time: datetime
) -> pd.DataFrame | None:
    """
    Fetch OUTCOME_WINDOW_BARS closed 1H candles starting AFTER signal_time.
    
    Args:
        symbol: Forex symbol (e.g., 'EURUSD')
        signal_time: The signal timestamp
        
    Returns:
        DataFrame with exactly OUTCOME_WINDOW_BARS candles, or None if not enough
    """
    lookback = OUTCOME_WINDOW_BARS + CANDLE_FETCH_BUFFER
    
    broker_timeframe = TIMEFRAMES.get(TIMEFRAME_1H)
    if broker_timeframe is None:
        logger.error(f"  ❌ {TIMEFRAME_1H} timeframe not configured")
        return None
    
    df = fetch_data(
        symbol,
        broker_timeframe,
        lookback=lookback,
        timeframe_label=TIMEFRAME_1H,
    )
    
    if df is None or df.empty:
        return None
    
    # Normalize signal_time to UTC
    signal_time_utc = (
        signal_time.astimezone(timezone.utc)
        if signal_time.tzinfo
        else signal_time.replace(tzinfo=timezone.utc)
    )
    
    # Filter to candles AFTER signal_time
    # A candle's 'time' represents its open time
    future_candles = df[df["time"] > signal_time_utc].copy()
    
    if len(future_candles) < OUTCOME_WINDOW_BARS:
        return None
    
    # Return exactly OUTCOME_WINDOW_BARS candles
    return future_candles.head(OUTCOME_WINDOW_BARS)
