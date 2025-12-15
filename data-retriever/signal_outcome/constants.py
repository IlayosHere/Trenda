"""Constants for signal outcome computation."""

from enum import Enum
from typing import Final, Literal

# --- Outcome Window ---
OUTCOME_WINDOW_BARS: Final[int] = 48

# --- Batch Processing ---
BATCH_SIZE: Final[int] = 100

# --- Candle Fetching ---
CANDLE_FETCH_BUFFER: Final[int] = 2000  #TODO: change  back Extra candles to fetch for weekend gaps
TIMEFRAME_1H: Final[str] = "1H"

# --- Checkpoint Returns ---
CHECKPOINT_BAR_3: Final[int] = 3
CHECKPOINT_BAR_6: Final[int] = 6
CHECKPOINT_BAR_12: Final[int] = 12
CHECKPOINT_BAR_24: Final[int] = 24
CHECKPOINT_BARS: Final[tuple[int, ...]] = (
    CHECKPOINT_BAR_3,
    CHECKPOINT_BAR_6,
    CHECKPOINT_BAR_12,
    CHECKPOINT_BAR_24,
)

# --- Weekend Days (for trading hours) ---
SATURDAY: Final[int] = 5
SUNDAY: Final[int] = 6
WEEKEND_DAYS: Final[tuple[int, int]] = (SATURDAY, SUNDAY)


# --- First Extreme Types ---
class FirstExtreme(str, Enum):
    """Which extreme (MFE or MAE) was reached first."""
    
    MFE_FIRST = "MFE_FIRST"
    MAE_FIRST = "MAE_FIRST"
    ONLY_MFE = "ONLY_MFE"
    ONLY_MAE = "ONLY_MAE"
    NONE = "NONE"


# --- Processing Result Types ---
class ProcessResult(str, Enum):
    """Result of processing a single signal."""
    
    PROCESSED = "processed"
    NOT_READY = "not_ready"
    MISSING_CANDLES = "missing_candles"
    ERROR = "error"


# Type alias for first extreme values
FirstExtremeType = Literal["MFE_FIRST", "MAE_FIRST", "ONLY_MFE", "ONLY_MAE", "NONE"]


# --- AOI Stop Loss ---
AOI_SL_TOLERANCE_ATR: Final[float] = 0.25


# --- R Target Multipliers ---
R_MULTIPLIER_1: Final[float] = 1.0
R_MULTIPLIER_1_5: Final[float] = 1.5
R_MULTIPLIER_2: Final[float] = 2.0
R_MULTIPLIERS: Final[tuple[float, ...]] = (R_MULTIPLIER_1, R_MULTIPLIER_1_5, R_MULTIPLIER_2)


# --- AOI R:R Outcome Types ---
class AoiRrOutcome(str, Enum):
    """Classification of R:R outcome - what happened first."""
    
    TP1_BEFORE_SL = "TP1_BEFORE_SL"
    TP1_5_BEFORE_SL = "TP1_5_BEFORE_SL"
    TP2_BEFORE_SL = "TP2_BEFORE_SL"
    SL_BEFORE_ANY_TP = "SL_BEFORE_ANY_TP"
    NONE = "NONE"

