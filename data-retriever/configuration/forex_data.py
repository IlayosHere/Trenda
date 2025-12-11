from dataclasses import dataclass
from typing import Mapping

import MetaTrader5 as mt5


@dataclass(frozen=True)
class AnalysisParams:
    lookback: int
    distance: int
    prominence: float
    aoi_lookback: int | None = None

FOREX_PAIRS = [
    # "EURUSD",
    # "GBPUSD",
    "USDJPY",
    # "USDCHF",
    # "USDCAD",
    # "AUDUSD",
    # "NZDUSD",
    # "GBPCAD",
    # "EURJPY",
    # "GBPJPY",
    # "AUDJPY",
    # "CADJPY",
    # "NZDJPY",
    # "CHFJPY",
    # "EURAUD",
    # "EURNZD",
    # "EURGBP",
    # "EURCHF",
    # "GBPAUD",
    # "GBPNZD",
    # "AUDNZD",
    # "AUDCAD",
    # "NZDCAD"
    ]

# 2. Define the timeframes you want to analyze
TIMEFRAMES = {
    "1W": mt5.TIMEFRAME_W1,
    "1D": mt5.TIMEFRAME_D1,
    "4H": mt5.TIMEFRAME_H4,
    "1H": mt5.TIMEFRAME_H1,
}

# 3. !! CRITICAL TUNING !!
# You MUST adjust 'distance' and 'prominence' for each timeframe.
# These values are just *examples* to get you started.
# Use the visual plotting method we discussed to find the right values.
ANALYSIS_PARAMS: Mapping[str, AnalysisParams] = {
    # timeframe: {lookback_candles, distance_filter, prominence_filter_in_pips}
    # (Note: prominence is in price units, e.g., 0.0010 for EURUSD)
    "1W": AnalysisParams(lookback=100, distance=1, prominence=0.0004),  # ~1 year
    "1D": AnalysisParams(
        lookback=100, aoi_lookback=140, distance=1, prominence=0.0004
    ),  # ~1 year
    "4H": AnalysisParams(
        lookback=100, aoi_lookback=180, distance=1, prominence=0.0004
    ),  # ~1.5 months
    "1H": AnalysisParams(lookback=150, distance=1, prominence=0.0004),
}


def require_analysis_params(timeframe: str) -> AnalysisParams:
    if timeframe not in ANALYSIS_PARAMS:
        raise KeyError(f"Unknown timeframe {timeframe!r} in ANALYSIS_PARAMS.")

    return ANALYSIS_PARAMS[timeframe]


def require_aoi_lookback(timeframe: str) -> int:
    params = require_analysis_params(timeframe)
    if params.aoi_lookback is None:
        raise ValueError(f"AOI lookback not configured for timeframe {timeframe!r}.")

    return params.aoi_lookback
