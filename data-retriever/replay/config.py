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
    "NZDCAD"
    ]

# =============================================================================
# Replay Window
# =============================================================================
REPLAY_START_DATE: Final[datetime] = datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
REPLAY_END_DATE: Final[datetime] = datetime(2025, 12, 26, 9, 0, 0, tzinfo=timezone.utc)

# Maximum days per chunk to avoid TwelveData's 5000 candle limit
# 120 days * 24 hours = 2880 1H candles (safe margin)
MAX_CHUNK_DAYS: Final[int] = 120

# =============================================================================
# SL/TP Model Versions
# =============================================================================
# These constants identify the current model logic for SL and TP calculations.
# Signals are filtered by these versions when fetching pending outcomes.
SL_MODEL_VERSION: Final[str] = 'ADD_AOI_CHECK'
TP_MODEL_VERSION: Final[str] = 'ADD_AOI_CHECK'

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

# =============================================================================
# Pre-Entry Context Windows
# =============================================================================
# Main lookback window for most pre-entry metrics
PRE_ENTRY_LOOKBACK_BARS: Final[int] = 20

# Short-term impulse window for detecting sudden moves
PRE_ENTRY_IMPULSE_BARS: Final[int] = 5

# Window for large bar ratio computation
PRE_ENTRY_LARGE_BAR_WINDOW: Final[int] = 10

# Long window for ATR ratio baseline (median ATR comparison)
PRE_ENTRY_LONG_ATR_WINDOW: Final[int] = 200

# =============================================================================
# Pre-Entry Context V2 Configuration
# =============================================================================
# Impulse detection threshold (directional push >= this ATR)
PRE_ENTRY_V2_IMPULSE_THRESHOLD_ATR: Final[float] = 0.8

# Large bar multiplier (body >= multiplier × average body size)
PRE_ENTRY_V2_LARGE_BAR_MULTIPLIER: Final[float] = 1.5

# Lookback for AOI reaction strength after exit
PRE_ENTRY_V2_AOI_REACTION_LOOKBACK: Final[int] = 100

# Lookback for impulse counting
PRE_ENTRY_V2_IMPULSE_LOOKBACK: Final[int] = 50

# Session definitions (UTC hours)
# Asia: 00:00-06:00, London: 06:00-12:00, NY: 12:00-18:00
SESSION_ASIA_START: Final[int] = 0
SESSION_ASIA_END: Final[int] = 6
SESSION_LONDON_START: Final[int] = 6
SESSION_LONDON_END: Final[int] = 12
SESSION_NY_START: Final[int] = 12
SESSION_NY_END: Final[int] = 18
