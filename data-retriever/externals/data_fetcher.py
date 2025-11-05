from typing import Any, Dict, List, Optional

import pandas as pd

from constants import DATA_ERROR_MSG
from externals.twelvedata_client import TwelveDataAPIError, fetch_forex_candles


def fetch_data(
    symbol: str, timeframe_config: Dict[str, Any], lookback: int
) -> Optional[pd.DataFrame]:
    """Fetch OHLC data from Twelve Data and convert it into a pandas DataFrame."""

    interval = timeframe_config["interval"]

    try:
        candles = fetch_forex_candles(symbol, interval, lookback)
    except TwelveDataAPIError as api_error:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} ({api_error})")
        return None

    if not candles:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} on TF {interval} (no data returned)")
        return None

    return _convert_to_dataframe(candles)


def _convert_to_dataframe(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert Twelve Data candle payload into a time-indexed DataFrame."""

    df = pd.DataFrame.from_records(candles)

    if df.empty:
        return df

    df.rename(columns={"datetime": "time"}, inplace=True)

    df["time"] = pd.to_datetime(df["time"], utc=True)

    for column in ("open", "high", "low", "close", "volume"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = pd.NA

    df.set_index("time", inplace=True)
    df.sort_index(inplace=True)
    return df
