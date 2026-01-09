from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
import tzlocal

from configuration.broker_config import (
    BROKER_MT5,
    BROKER_PROVIDER,
    BROKER_TWELVEDATA,
    TWELVEDATA_API_KEY,
    TWELVEDATA_BASE_URL,
)
from constants import DATA_ERROR_MSG
from utils.candles import last_expected_close_time, trim_to_closed_candles

if BROKER_PROVIDER == BROKER_MT5:
    import MetaTrader5 as mt5
else:  # Avoid import errors when MT5 isn't needed
    mt5 = None  # type: ignore[assignment]


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
    Fetch OHLC data from the configured broker, returning a dataframe of candles.

    When ``timeframe_label`` is provided, any candles whose timestamps extend
    beyond the last expected close for that timeframe are dropped to ensure only
    closed candles are returned.
    
    Args:
        end_date: Optional end date for historical data fetching (TwelveData only).
                  If provided, fetches `lookback` candles ending at this date.
    """

    if BROKER_PROVIDER == BROKER_MT5:
        df = _fetch_from_mt5(symbol, timeframe, lookback, end_date=end_date)
    elif BROKER_PROVIDER == BROKER_TWELVEDATA:
        df = _fetch_from_twelvedata(symbol, timeframe, lookback, end_date=end_date)
    else:  # pragma: no cover - defensive fallback
        raise ValueError(f"Unsupported broker provider {BROKER_PROVIDER!r}")

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
        end_date: If provided, fetches `lookback` candles ending at this date
                  using copy_rates_range. Otherwise uses current position.
    """
    if mt5 is None:
        print("  ❌ MetaTrader5 is not available in this environment.")
        return None

    tf_int = int(timeframe_mt5)
    
    if end_date is not None:
        # Calculate start_date based on lookback and timeframe
        # Use copy_rates_range for historical date-based fetching
        from datetime import timedelta
        
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
                print(f"  ⚠️ MT5 error for {symbol} TF {tf_int}: code={error[0]}, msg={error[1]}")
                print(f"      Date range: {start_date} to {end_date_naive}")
    else:
        rates = mt5.copy_rates_from_pos(symbol, tf_int, 0, lookback)

    if rates is None or len(rates) == 0:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} on TF {timeframe_mt5}")
        return None

    local_tz = tzlocal.get_localzone_name()
    df = pd.DataFrame(rates)
    
    # MT5 timestamps are in BROKER LOCAL TIME (often EET/EEST, UTC+2/+3)
    # but encoded as Unix timestamps without proper UTC conversion.
    # We need to subtract the broker's UTC offset to get true UTC times.
    from configuration.broker_config import MT5_BROKER_UTC_OFFSET
    broker_offset_seconds = MT5_BROKER_UTC_OFFSET * 3600
    
    # Convert to datetime and correct for broker timezone
    df["time"] = pd.to_datetime(df["time"] - broker_offset_seconds, unit="s", utc=True)
    
    # If we used date range, trim to requested lookback
    if end_date is not None and len(df) > lookback:
        df = df.tail(lookback)
    
    return df



def _fetch_from_twelvedata(
    symbol: str,
    interval: str | int,
    lookback: int,
    *,
    end_date: datetime | None = None,
) -> Optional[pd.DataFrame]:
    if TWELVEDATA_API_KEY is None:
        print("  ❌ TWELVEDATA_API_KEY is not set; cannot fetch data.")
        return None

    formatted_symbol = _format_twelvedata_symbol(symbol)
    
    # Build request params
    params = {
        "symbol": formatted_symbol,
        "interval": interval,
        "outputsize": lookback,
        "apikey": TWELVEDATA_API_KEY,
        "timezone": "UTC",
    }
    
    # Add end_date for historical data fetching
    if end_date is not None:
        # Format as ISO string for TwelveData API
        params["end_date"] = end_date.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # TwelveData documents Forex time-series access through the dedicated
        # ``/forex/time_series`` endpoint with the pair encoded as "BASE/QUOTE".
        response = requests.get(
            f"{TWELVEDATA_BASE_URL.rstrip('/')}/time_series",
            params=params,
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"  ❌ Failed to fetch TwelveData candles for {symbol}: {exc}")
        return None

    payload = response.json()
    if payload.get("status") == "error":
        print(
            f"  ❌ TwelveData error for {symbol}: {payload.get('message', 'Unknown error')}"
        )
        return None

    values = payload.get("values")
    if not values:
        print(f"  ❌ No TwelveData candles returned for {symbol} ({interval}).")
        return None

    df = pd.DataFrame(values)
    df = df.rename(columns={"datetime": "time"})
    numeric_cols = ["open", "high", "low", "close"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.dropna(subset=["time", *numeric_cols])
    df = df.sort_values("time").tail(lookback)
    return df


def _format_twelvedata_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if len(symbol) == 6:
        return f"{symbol[:3]}/{symbol[3:]}"
    return symbol
