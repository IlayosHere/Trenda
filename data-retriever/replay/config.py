"""Replay engine configuration and constants.

All parameters are locked to ensure deterministic replay behavior.
Values are sourced from production configuration where applicable.
"""

from datetime import datetime, timezone
from typing import Final

# =============================================================================
# Replay Symbols
# =============================================================================
REPLAY_SYMBOLS: Final[list[str]] = [
    # "EURUSD",
    # "USDJPY",
    # "GBPUSD",
    # "USDCHF",
    # "USDCAD",
    # "AUDUSD",
    # "NZDUSD",
    # "GBPCAD",
    # "EURJPY",
    # "GBPJPY",
    # "AUDJPY",
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
    "NZDCAD"
    ]

# =============================================================================
# Replay Window
# =============================================================================
REPLAY_START_DATE: Final[datetime] = datetime(2025, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
REPLAY_END_DATE: Final[datetime] = datetime(2025, 12, 17, 23, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# Lookback Sizes (must match production: configuration/forex_data.py)
# =============================================================================
# 1H pattern lookback for entry detection
LOOKBACK_1H: Final[int] = 15

# Trend lookbacks for each timeframe
LOOKBACK_4H: Final[int] = 100
LOOKBACK_1D: Final[int] = 100
LOOKBACK_1W: Final[int] = 100

# AOI lookbacks (aoi_lookback from ANALYSIS_PARAMS)
LOOKBACK_AOI_4H: Final[int] = 180
LOOKBACK_AOI_1D: Final[int] = 140

# =============================================================================
# Outcome Window
# =============================================================================
OUTCOME_WINDOW_BARS: Final[int] = 168  # 7 days * 24 hours

# =============================================================================
# Execution Constants (from signal_outcome/constants.py)
# =============================================================================
AOI_SL_TOLERANCE_ATR: Final[float] = 0.25

# =============================================================================
# Tier Thresholds (from entry/quality/components.py)
# =============================================================================
TIER_PRIORITY_THRESHOLD: Final[float] = 0.72
TIER_NOTIFY_THRESHOLD: Final[float] = 0.60
TIER_WATCHLIST_THRESHOLD: Final[float] = 0.45

# =============================================================================
# Database Configuration
# =============================================================================
SCHEMA_NAME: Final[str] = "trenda_replay"

# =============================================================================
# Timeframe Definitions
# =============================================================================
TIMEFRAME_1H: Final[str] = "1H"
TIMEFRAME_4H: Final[str] = "4H"
TIMEFRAME_1D: Final[str] = "1D"
TIMEFRAME_1W: Final[str] = "1W"

# Timeframe intervals in hours (for alignment calculations)
TIMEFRAME_HOURS: Final[dict[str, int]] = {
    TIMEFRAME_1H: 1,
    TIMEFRAME_4H: 4,
    TIMEFRAME_1D: 24,
    TIMEFRAME_1W: 168,  # 24 * 7
}

# Trend alignment timeframes (order matters for overall trend calculation)
TREND_ALIGNMENT_TIMEFRAMES: Final[tuple[str, ...]] = ("4H", "1D", "1W")

# =============================================================================
# TwelveData API Intervals
# =============================================================================
TWELVEDATA_INTERVALS: Final[dict[str, str]] = {
    TIMEFRAME_1H: "1h",
    TIMEFRAME_4H: "4h",
    TIMEFRAME_1D: "1day",
    TIMEFRAME_1W: "1week",
}

# =============================================================================
# Batch Processing
# =============================================================================
BATCH_SIZE: Final[int] = 100
CANDLE_FETCH_BUFFER: Final[int] = 50  # Extra candles for weekend gaps
