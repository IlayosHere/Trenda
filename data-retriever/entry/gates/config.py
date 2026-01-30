import os
from typing import Final, Tuple
from configuration.trading_config import SIGNAL_SCORE_THRESHOLD

# =============================================================================
# Gate 2: Timeframe Conflict Filter
# =============================================================================
# Exclude signals where this timeframe conflicts with the trade direction
EXCLUDED_CONFLICTED_TF: Final[str] = os.getenv("EXCLUDED_CONFLICTED_TF", "4H")

# =============================================================================
# Gate 3: HTF Range Alignment
# =============================================================================
# Bullish trades require position at lower end of range
MAX_BULLISH_DAILY_POSITION: Final[float] = float(os.getenv("MAX_BULLISH_DAILY_POSITION", "0.33"))
MAX_BULLISH_WEEKLY_POSITION: Final[float] = float(os.getenv("MAX_BULLISH_WEEKLY_POSITION", "0.50"))

# Bearish trades require position at upper end of range
MIN_BEARISH_DAILY_POSITION: Final[float] = float(os.getenv("MIN_BEARISH_DAILY_POSITION", "0.67"))
MIN_BEARISH_WEEKLY_POSITION: Final[float] = float(os.getenv("MIN_BEARISH_WEEKLY_POSITION", "0.50"))

# =============================================================================
# Gate 4: Obstacle Clearance
# =============================================================================
# Minimum distance to next HTF obstacle (in ATR units)
MIN_OBSTACLE_DISTANCE_ATR: Final[float] = float(os.getenv("MIN_OBSTACLE_DISTANCE_ATR", "1.0"))

# Default value when no obstacles found
NO_OBSTACLE_DISTANCE_ATR: Final[float] = 10.0

# =============================================================================
# Scoring Configuration
# =============================================================================
# HTF Range Score thresholds for bullish (position <= threshold -> score)
BULLISH_SCORE_THRESHOLDS: Final[Tuple[Tuple[float, float], ...]] = (
    (0.25, 3.0),  # <= 0.25 → 3
    (0.28, 2.0),  # <= 0.28 → 2
    (0.32, 1.0),  # <= 0.32 → 1
)

# HTF Range Score thresholds for bearish (position >= threshold -> score)
BEARISH_SCORE_THRESHOLDS: Final[Tuple[Tuple[float, float], ...]] = (
    (0.75, 3.0),  # >= 0.75 → 3
    (0.72, 2.0),  # >= 0.72 → 2
    (0.68, 1.0),  # >= 0.68 → 1
)

# Fixed obstacle score (since gate already ensures >= 1.0 ATR)
FIXED_OBSTACLE_SCORE: Final[float] = float(os.getenv("FIXED_OBSTACLE_SCORE", "3.0"))

# Minimum total score to pass
MIN_TOTAL_SCORE: Final[float] = SIGNAL_SCORE_THRESHOLD

# =============================================================================
# SL/TP Configuration
# =============================================================================
# SL Model: distance to far edge of AOI + buffer in ATR
SL_MODEL_NAME: Final[str] = os.getenv("SL_MODEL_NAME", "SL_AOI_FAR_PLUS_0_25")
SL_BUFFER_ATR: Final[float] = float(os.getenv("SL_BUFFER_ATR", "0.25"))

# Risk-Reward multiple for take profit
RR_MULTIPLE: Final[float] = float(os.getenv("RR_MULTIPLE", "2.0"))

# =============================================================================
# HTF Context Configuration
# =============================================================================
# Timeframes to fetch for HTF context (in order)
HTF_TIMEFRAMES: Final[Tuple[str, ...]] = ("4H", "1D", "1W")

# Timeframes used for range position calculation
RANGE_POSITION_TIMEFRAMES: Final[Tuple[str, ...]] = ("1D", "1W")
