from dataclasses import dataclass
from typing import Final, Literal

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
TrendBias = Literal["bullish", "bearish", "neutral"]
TREND_BULLISH: Final[TrendBias] = "bullish"
TREND_BEARISH: Final[TrendBias] = "bearish"
TREND_NEUTRAL: Final[TrendBias] = "neutral"

# --- Structure Break Constants ---
BREAK_BULLISH: str = "BULLISH_BREAK"
BREAK_BEARISH: str = "BEARISH_BREAK"
NO_BREAK: str = "NO_BREAK"

# --- Error/Status Constants ---
DATA_ERROR_MSG: str = "Data Error"
