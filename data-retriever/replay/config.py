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
REPLAY_START_DATE: Final[datetime] = datetime(2012, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
REPLAY_END_DATE: Final[datetime] = datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# Maximum days per chunk to avoid TwelveData's 5000 candle limit
# 120 days * 24 hours = 2880 1H candles (safe margin)
MAX_CHUNK_DAYS: Final[int] = 120

# =============================================================================
# SL/TP Model Versions
# =============================================================================
# These constants identify the current model logic for SL and TP calculations.
# Signals are filtered by these versions when fetching pending outcomes.
SL_MODEL_VERSION: Final[str] = 'SL_2'
TP_MODEL_VERSION: Final[str] = 'TP_2'

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
OUTCOME_WINDOW_BARS: Final[int] = 72  # 72 hours (3 days)

# =============================================================================
# Exit Simulation Configuration
# =============================================================================
# SL models for exit simulation (sl_atr calculation varies by model)
# Note: For PLUS_X models, the buffer pushes SL further from entry
SL_MODELS: Final[list[str]] = [
    # Fixed ATR-based SL distances
    "SL_ATR_0_1",                   # sl_atr = 0.1
    "SL_ATR_0_2",                   # sl_atr = 0.2
    "SL_ATR_0_3",                   # sl_atr = 0.3
    "SL_ATR_0_4",                   # sl_atr = 0.4
    "SL_ATR_0_5",                   # sl_atr = 0.5
    "SL_ATR_0_6",                   # sl_atr = 0.6
    "SL_ATR_0_7",                   # sl_atr = 0.7
    "SL_ATR_0_8",                   # sl_atr = 0.8
    "SL_ATR_0_9",                   # sl_atr = 0.9
    "SL_ATR_1_0",                   # sl_atr = 1.0
    "SL_ATR_1_1",                   # sl_atr = 1.1
    "SL_ATR_1_2",                   # sl_atr = 1.2
    "SL_ATR_1_5",                   # sl_atr = 1.5
    # AOI-based SL distances
    "SL_AOI_FAR",                   # sl_atr = aoi_far_edge_atr
    "SL_AOI_FAR_PLUS_0_25",         # sl_atr = aoi_far_edge_atr + 0.25
    "SL_AOI_NEAR",                  # sl_atr = aoi_near_edge_atr
    "SL_AOI_NEAR_PLUS_0_25",        # sl_atr = aoi_near_edge_atr + 0.25
    # Signal candle-based SL distances
    "SL_SIGNAL_CANDLE",             # sl_atr = signal_candle_opposite_extreme_atr
    "SL_SIGNAL_CANDLE_PLUS_0_1",    # sl_atr = signal_candle + 0.1
    "SL_SIGNAL_CANDLE_PLUS_0_2",    # sl_atr = signal_candle + 0.2
    "SL_SIGNAL_CANDLE_PLUS_0_25",   # sl_atr = signal_candle + 0.25
    "SL_SIGNAL_CANDLE_PLUS_0_3",    # sl_atr = signal_candle + 0.3
    "SL_SIGNAL_CANDLE_PLUS_0_4",    # sl_atr = signal_candle + 0.4
    "SL_SIGNAL_CANDLE_PLUS_0_5",    # sl_atr = signal_candle + 0.5
    # Hybrid SL model
    "SL_MAX_AOI_ATR_1_0",           # sl_atr = max(aoi_far_edge_atr, 1.0)
]

# R multiples for take profit calculation (tp_atr = sl_atr × rr_multiple)
RR_MULTIPLES: Final[list[float]] = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]

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
# Broker-Specific API Intervals
# =============================================================================
# TwelveData uses string intervals, MT5 uses integer constants
TWELVEDATA_INTERVALS: Final[dict[str, str]] = {
    TIMEFRAME_1H: "1h",
    TIMEFRAME_4H: "4h",
    TIMEFRAME_1D: "1day",
    TIMEFRAME_1W: "1week",
}

# MT5 timeframe constants (from MetaTrader5.TIMEFRAME_*)
MT5_INTERVALS: Final[dict[str, int]] = {
    TIMEFRAME_1H: 16385,   # TIMEFRAME_H1
    TIMEFRAME_4H: 16388,   # TIMEFRAME_H4
    TIMEFRAME_1D: 16408,   # TIMEFRAME_D1
    TIMEFRAME_1W: 32769,   # TIMEFRAME_W1
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
