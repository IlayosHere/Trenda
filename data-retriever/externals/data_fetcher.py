from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd
import tzlocal

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
    closed_candles_only: bool = True
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

    if closed_candles_only: 
        cutoff_time = last_expected_close_time(
            timeframe_label, now=now or datetime.now(timezone.utc)
        )
        trimmed = trim_to_closed_candles(df, timeframe_label, now=cutoff_time)
        return trimmed
    
    return df


def _convert_to_dataframe(rates: tuple) -> pd.DataFrame:
    """
    Converts the raw MT5 rates tuple into a time-indexed pandas DataFrame.

    Args:
        rates (tuple): Raw data from mt5.copy_rates_from_pos.

    Returns:
        pd.DataFrame: A clean, time-indexed DataFrame.
    """
    local_tz = tzlocal.get_localzone_name()
    df = pd.DataFrame(rates)
    df["time"] = (
        pd.to_datetime(df["time"], unit="s")
        .dt.tz_localize(local_tz)   # interpret raw timestamps as local MT5 time
        .dt.tz_convert("UTC")        # normalize to UTC
    )    # df.set_index("time", inplace=True)
    return df
