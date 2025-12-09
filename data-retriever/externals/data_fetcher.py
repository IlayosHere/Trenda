from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

# Import the error message constant
from constants import DATA_ERROR_MSG
from utils.candles import last_expected_close_time, trim_to_closed_candles


def fetch_data(
    symbol: str,
    timeframe_mt5: int,
    lookback: int,
    *,
    timeframe_label: str | None = None,
    now: datetime | None = None,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLC data from MT5, converting it into a dataframe of closed candles.

    When ``timeframe_label`` is provided, any candles whose timestamps extend
    beyond the last expected close for that timeframe are dropped to ensure only
    closed candles are returned.
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, lookback)

    if rates is None or len(rates) == 0:
        print(f"  ❌ {DATA_ERROR_MSG} for {symbol} on TF {timeframe_mt5}")
        return None

    df = _convert_to_dataframe(rates)

    if timeframe_label is None:
        return df

    cutoff_time = last_expected_close_time(
        timeframe_label, now=now or datetime.now(timezone.utc)
    )
    trimmed = trim_to_closed_candles(df, timeframe_label, now=cutoff_time)
    return trimmed


def _convert_to_dataframe(rates: tuple) -> pd.DataFrame:
    """
    Converts the raw MT5 rates tuple into a time-indexed pandas DataFrame.

    Args:
        rates (tuple): Raw data from mt5.copy_rates_from_pos.

    Returns:
        pd.DataFrame: A clean, time-indexed DataFrame.
    """
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # df.set_index("time", inplace=True)
    return df
