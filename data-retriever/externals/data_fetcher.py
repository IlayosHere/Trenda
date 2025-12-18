from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
import tzlocal

from configuration.broker import (
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
        df = _fetch_from_mt5(symbol, timeframe, lookback)
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


def _fetch_from_mt5(symbol: str, timeframe_mt5: int | str, lookback: int) -> Optional[pd.DataFrame]:
    if mt5 is None:
        print("  ❌ MetaTrader5 is not available in this environment.")
        return None

    rates = mt5.copy_rates_from_pos(symbol, int(timeframe_mt5), 0, lookback)

    if rates is None or len(rates) == 0:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} on TF {timeframe_mt5}")
        return None

    local_tz = tzlocal.get_localzone_name()
    df = pd.DataFrame(rates)
    df["time"] = (
        pd.to_datetime(df["time"], unit="s")
        .dt.tz_localize(local_tz)   # interpret raw timestamps as local MT5 time
        .dt.tz_convert("UTC")        # normalize to UTC
    )
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
