"""Technical indicator utilities."""

from __future__ import annotations

from typing import Union

import pandas as pd
import pandas_ta as ta


def calculate_atr(
    data: Union[pd.DataFrame, dict],
    length: int = 14,
) -> float:
    """Calculate ATR (Average True Range) for the given OHLC data.
    
    Args:
        data: DataFrame or dict containing 'high', 'low', 'close' columns/keys
        length: ATR period length (default: 14)
    
    Returns:
        Current ATR value as a float, or 0.0 if calculation fails
    """
    if isinstance(data, dict):
        df = pd.DataFrame({
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
        })
    else:
        df = data[["high", "low", "close"]].copy()
    
    if len(df) < length:
        return 0.0
    
    atr_series = ta.atr(df["high"], df["low"], df["close"], length=length)
    if atr_series is None or atr_series.empty:
        return 0.0
    
    current_atr = atr_series.iloc[-1]
    if pd.isna(current_atr):
        return 0.0
    
    return float(current_atr)
