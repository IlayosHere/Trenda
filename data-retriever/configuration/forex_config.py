"""Forex configuration - symbols, timeframes, and analysis parameters."""
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
    "EURUSD",
    "USDJPY",
    "GBPUSD",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "GBPCAD",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "CADJPY",
    "NZDJPY",
    "CHFJPY",
    "EURAUD",
    "EURNZD",
    "EURGBP",
    "EURCHF",
    "GBPAUD",
    "GBPNZD",
    "AUDNZD",
    "AUDCAD",
    "NZDCAD",
    "EURCAD",
    "CADCHF",
    "GBPCHF",
    "AUDCHF",
    "NZDCHF"
]

# MT5 timeframes
TIMEFRAMES = {
    "1W": mt5.TIMEFRAME_W1,
    "1D": mt5.TIMEFRAME_D1,
    "4H": mt5.TIMEFRAME_H4,
    "1H": mt5.TIMEFRAME_H1,
}

# Analysis parameters per timeframe
# CRITICAL TUNING: Adjust 'distance' and 'prominence' for each timeframe
ANALYSIS_PARAMS: Mapping[str, AnalysisParams] = {
    "1W": AnalysisParams(lookback=100, distance=1, prominence=0.0004),
    "1D": AnalysisParams(
        lookback=100, aoi_lookback=140, distance=1, prominence=0.0004
    ),
    "4H": AnalysisParams(
        lookback=100, aoi_lookback=180, distance=1, prominence=0.0004
    ),
    "1H": AnalysisParams(lookback=15, distance=1, prominence=0.0004),
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
