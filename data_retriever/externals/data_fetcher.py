from __future__ import annotations

from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from data_retriever.constants import DATA_ERROR_MSG
from data_retriever.utils import display


def fetch_data(
    symbol: str, timeframe_mt5: int, lookback: int
) -> Optional[pd.DataFrame]:
    """
    Fetches OHLC data from MT5 and converts it.

    Args:
        symbol (str): The financial instrument (e.g., "EURUSD").
        timeframe_mt5 (int): The MT5 timeframe constant.
        lookback (int): The number of candles to fetch.

    Returns:
        Optional[pd.DataFrame]: A time-indexed DataFrame, or None if fetching fails.
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, lookback)

    if rates is None or len(rates) == 0:
        display.print_error(
            f"{DATA_ERROR_MSG} for {symbol} on TF {timeframe_mt5}"
        )
        return None

    return _convert_to_dataframe(rates)


def _convert_to_dataframe(rates: tuple) -> pd.DataFrame:
    """
    Converts the raw MT5 rates tuple into a time-indexed pandas DataFrame.

    Args:
        rates (tuple): Raw data from mt5.copy_rates_from_pos.

    Returns:
        pd.DataFrame: A clean, time-indexed DataFrame.
    """
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df
