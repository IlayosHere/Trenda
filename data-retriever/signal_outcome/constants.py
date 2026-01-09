"""Constants for signal outcome computation."""

from enum import Enum
from typing import Final, Literal

# --- Outcome Window ---
OUTCOME_WINDOW_BARS: Final[int] = 96  # 4 days * 24 hours

# --- Batch Processing ---
BATCH_SIZE: Final[int] = 100

# --- Candle Fetching ---
CANDLE_FETCH_BUFFER: Final[int] = 200  # Extra candles to fetch for weekend gaps
TIMEFRAME_1H: Final[str] = "1H"

# --- Checkpoint Returns ---
# Checkpoints: 48h, 72h, 96h (end of window)
CHECKPOINT_BAR_48: Final[int] = 48
CHECKPOINT_BAR_72: Final[int] = 72
CHECKPOINT_BAR_96: Final[int] = 96
CHECKPOINT_BARS: Final[tuple[int, ...]] = (
    CHECKPOINT_BAR_48,
    CHECKPOINT_BAR_72,
    CHECKPOINT_BAR_96,
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


# --- Exit Reason Types ---
class ExitReason(str, Enum):
    """Exit reason for the trade."""
    
    SL = "SL"       # Stop loss hit
    TP = "TP"       # Take profit hit
    TIMEOUT = "TIMEOUT"  # No SL or TP within window


# --- Processing Result Types ---
class ProcessResult(str, Enum):
    """Result of processing a single signal."""
    
    PROCESSED = "processed"
    NOT_READY = "not_ready"
    MISSING_CANDLES = "missing_candles"
    ERROR = "error"


# Type alias for first extreme values
FirstExtremeType = Literal["MFE_FIRST", "MAE_FIRST", "ONLY_MFE", "ONLY_MAE", "NONE"]

# Type alias for exit reason values
ExitReasonType = Literal["SL", "TP", "TIMEOUT"]
