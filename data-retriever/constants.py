from dataclasses import dataclass
from typing import Final, Literal

from models import TrendDirection

# --- Type Definitions ---

SwingKind = Literal["H", "L"]
SWING_HIGH: Final[SwingKind] = "H"
SWING_LOW: Final[SwingKind] = "L"


@dataclass(frozen=True)
class SwingPoint:
    """Represents a significant swing point (high/low) in price data."""

    index: int
    price: float
    kind: SwingKind

# --- Trend Analysis Constants ---
TREND_BULLISH: Final[TrendDirection] = TrendDirection.BULLISH
TREND_BEARISH: Final[TrendDirection] = TrendDirection.BEARISH
TREND_NEUTRAL: Final[TrendDirection] = TrendDirection.NEUTRAL

# --- Structure Break Constants ---
BREAK_BULLISH: str = "BULLISH_BREAK"
BREAK_BEARISH: str = "BEARISH_BREAK"
NO_BREAK: str = "NO_BREAK"

# --- Error/Status Constants ---
DATA_ERROR_MSG: str = "Data Error"
