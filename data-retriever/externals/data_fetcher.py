from typing import Any, Dict, Optional

import pandas as pd

from constants import DATA_ERROR_MSG
from externals.finnhub_client import FinnhubAPIError, fetch_forex_candles


def fetch_data(
    symbol: str, timeframe_config: Dict[str, Any], lookback: int
) -> Optional[pd.DataFrame]:
    """Fetch OHLC data from Finnhub and convert it into a pandas DataFrame."""

    resolution = timeframe_config["resolution"]
    seconds_per_candle = timeframe_config["seconds"]

    try:
        candles = fetch_forex_candles(symbol, resolution, lookback, seconds_per_candle)
    except FinnhubAPIError as api_error:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} ({api_error})")
        return None

    if not candles:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} on TF {resolution} (no data returned)")
        return None

    return _convert_to_dataframe(candles)


def _convert_to_dataframe(candles: Dict[str, list]) -> pd.DataFrame:
    """Convert Finnhub candle arrays into a time-indexed DataFrame."""

    df = pd.DataFrame(
        {
            "time": candles.get("t", []),
            "open": candles.get("o", []),
            "high": candles.get("h", []),
            "low": candles.get("l", []),
            "close": candles.get("c", []),
            "volume": candles.get("v", []),
        }
    )

    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df
