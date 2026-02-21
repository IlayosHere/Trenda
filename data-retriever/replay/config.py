"""Replay engine configuration and constants.

All parameters are locked to ensure deterministic replay behavior.
Values are sourced from production configuration where applicable.
"""

import os
from dataclasses import dataclass
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
    # "AUDNZD",
    "AUDCAD",
    "NZDCAD",
    "EURCAD",
    # "CADCHF",
    "GBPCHF",
    "AUDCHF",
    "NZDCHF",
    # "EURPLN", 
    "NZDSGD",
    # "SGDJPY"
    ]

# =============================================================================
# Replay Window
# =============================================================================
REPLAY_START_DATE: Final[datetime] = datetime(2023,1, 1, 0, 0, 0, tzinfo=timezone.utc)
REPLAY_END_DATE: Final[datetime] = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# Maximum days per chunk to avoid terminal candle limits (typically 5000)
# 120 days * 24 hours = 2880 1H candles (safe margin)
MAX_CHUNK_DAYS: Final[int] = 120

# =============================================================================
# SL/TP Model Versions
# =============================================================================
# Production model configuration (must match entry/gates/config.py)
SL_MODEL_VERSION: Final[str] = 'CHECK_GEO'
TP_MODEL_VERSION: Final[str] = 'NO_BIAS'

# =============================================================================
# Lookback Sizes (must match production: configuration/forex_data.py)
# =============================================================================
# 1H pattern lookback for entry detection
LOOKBACK_1H: Final[int] = 25

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
OUTCOME_WINDOW_BARS: Final[int] = 120  # 120 hours (5 days)

# Checkpoint bars for return calculation
CHECKPOINT_BARS: Final[list[int]] = [3, 6, 12, 24, 48, 72]

# =============================================================================
# Exit Simulation Configuration (Comprehensive Testing)
# =============================================================================
# 12 SL models × 6 RR multiples = 72 rows per signal
SL_MODELS: Final[list[str]] = [
    # Fixed ATR-based (4)
    "SL_ATR_0_5",
    "SL_ATR_1_0",
    "SL_ATR_1_5",
    "SL_ATR_2_0",
    # AOI-based (6) - expanded
    "SL_AOI_FAR",
    "SL_AOI_FAR_PLUS_0_25",
    # "SL_AOI_FAR_PLUS_0_5",
    "SL_AOI_NEAR",
    "SL_AOI_NEAR_PLUS_0_25",
    "SL_AOI_NEAR_PLUS_0_5",
    # Signal candle-based (2)
    "SL_SIGNAL_CANDLE",
    "SL_SIGNAL_CANDLE_PLUS_0_25",
]

# RR multiples: clean numbers from 1.0 to 4.0
RR_MULTIPLES: Final[list[float]] = [2.0, 2.5, 3.0, 3.5, 4.0]

# =============================================================================
# Database Configuration
# =============================================================================
SCHEMA_NAME: Final[str] = "trenda_replay"

# =============================================================================
# Timeframe Definitions
# =============================================================================
TIMEFRAME_15M: Final[str] = "15M"
TIMEFRAME_1H: Final[str] = "1H"
TIMEFRAME_4H: Final[str] = "4H"
TIMEFRAME_1D: Final[str] = "1D"
TIMEFRAME_1W: Final[str] = "1W"

# Timeframe intervals in hours (for alignment calculations)
TIMEFRAME_HOURS: Final[dict[str, float]] = {
    TIMEFRAME_15M: 0.25,
    TIMEFRAME_1H: 1,
    TIMEFRAME_4H: 4,
    TIMEFRAME_1D: 24,
    TIMEFRAME_1W: 168,  # 24 * 7
}

# =============================================================================
# MT5 Timeframe Intervals
# =============================================================================
# MT5 timeframe constants (from MetaTrader5.TIMEFRAME_*)
MT5_INTERVALS: Final[dict[str, int]] = {
    TIMEFRAME_15M: 16387,  # TIMEFRAME_M15
    TIMEFRAME_1H: 16385,   # TIMEFRAME_H1
    TIMEFRAME_4H: 16388,   # TIMEFRAME_H4
    TIMEFRAME_1D: 16408,   # TIMEFRAME_D1
    TIMEFRAME_1W: 32769,   # TIMEFRAME_W1
}

# =============================================================================
# Timeframe Profile System
# =============================================================================
# Controls which timeframes are used for trend, AOI, and entry detection.
# Set env var REPLAY_TF_PROFILE to switch profiles.
#
# DEFAULT: Trend=4H/1D/1W, AOI=4H/1D, Entry=1H  (original)
# LOWER:   Trend=1H/4H/1D, AOI=1H/4H, Entry=15M  (faster TFs)


@dataclass(frozen=True)
class TimeframeProfile:
    """Defines which timeframes fill each role in the replay engine."""

    name: str

    # Trend timeframes: low → mid → high (order matters for alignment)
    trend_tf_low: str
    trend_tf_mid: str
    trend_tf_high: str

    # AOI detection timeframes
    aoi_tf_low: str
    aoi_tf_high: str

    # Entry detection / main iteration timeframe
    entry_tf: str

    # Lookbacks per role
    lookback_trend_low: int
    lookback_trend_mid: int
    lookback_trend_high: int
    lookback_aoi_low: int
    lookback_aoi_high: int
    lookback_entry: int

    @property
    def trend_alignment_tfs(self) -> tuple[str, ...]:
        """Trend TFs in low→high order for alignment calculation."""
        return (self.trend_tf_low, self.trend_tf_mid, self.trend_tf_high)

    @property
    def all_required_timeframes(self) -> tuple[str, ...]:
        """All unique timeframes that must be loaded by CandleStore."""
        seen: list[str] = []
        for tf in (self.entry_tf, self.trend_tf_low, self.trend_tf_mid,
                   self.trend_tf_high, self.aoi_tf_low, self.aoi_tf_high):
            if tf not in seen:
                seen.append(tf)
        return tuple(seen)

    def lookback_for_trend(self, tf: str) -> int:
        """Return the trend lookback for a given timeframe."""
        if tf == self.trend_tf_low:
            return self.lookback_trend_low
        if tf == self.trend_tf_mid:
            return self.lookback_trend_mid
        if tf == self.trend_tf_high:
            return self.lookback_trend_high
        raise ValueError(f"Unknown trend TF: {tf}")

    def lookback_for_aoi(self, tf: str) -> int:
        """Return the AOI lookback for a given timeframe."""
        if tf == self.aoi_tf_low:
            return self.lookback_aoi_low
        if tf == self.aoi_tf_high:
            return self.lookback_aoi_high
        raise ValueError(f"Unknown AOI TF: {tf}")


PROFILE_DEFAULT = TimeframeProfile(
    name="DEFAULT",
    trend_tf_low=TIMEFRAME_4H, trend_tf_mid=TIMEFRAME_1D, trend_tf_high=TIMEFRAME_1W,
    aoi_tf_low=TIMEFRAME_4H, aoi_tf_high=TIMEFRAME_1D,
    entry_tf=TIMEFRAME_1H,
    lookback_trend_low=LOOKBACK_4H, lookback_trend_mid=LOOKBACK_1D, lookback_trend_high=LOOKBACK_1W,
    lookback_aoi_low=LOOKBACK_AOI_4H, lookback_aoi_high=LOOKBACK_AOI_1D,
    lookback_entry=LOOKBACK_1H,
)

PROFILE_LOWER = TimeframeProfile(
    name="LOWER",
    trend_tf_low=TIMEFRAME_1H, trend_tf_mid=TIMEFRAME_4H, trend_tf_high=TIMEFRAME_1D,
    aoi_tf_low=TIMEFRAME_1H, aoi_tf_high=TIMEFRAME_4H,
    entry_tf=TIMEFRAME_15M,
    lookback_trend_low=100, lookback_trend_mid=100, lookback_trend_high=100,
    lookback_aoi_low=180, lookback_aoi_high=180,
    lookback_entry=100,  # 100 × 15M = 25 hours
)

_PROFILES = {"DEFAULT": PROFILE_DEFAULT, "LOWER": PROFILE_LOWER}
_profile_name = os.environ.get("REPLAY_TF_PROFILE", "DEFAULT").upper()
ACTIVE_PROFILE: TimeframeProfile = _PROFILES.get(_profile_name, PROFILE_DEFAULT)

# Legacy alias — consumed by trend.bias and other modules
TREND_ALIGNMENT_TIMEFRAMES: Final[tuple[str, ...]] = ACTIVE_PROFILE.trend_alignment_tfs

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
