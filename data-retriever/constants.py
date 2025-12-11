from dataclasses import dataclass
from typing import Literal

# --- Type Definitions ---


SWING_HIGH: str = "H"
SWING_LOW: str = "L"
SwingKind = Literal[SWING_HIGH, SWING_LOW]


@dataclass(frozen=True)
class SwingPoint:
    """Represents a significant swing point (high/low) in price data."""

    index: int
    price: float
    kind: SwingKind

# --- Trend Analysis Constants ---
TREND_BULLISH: str = "bullish"
TREND_BEARISH: str = "bearish"
TREND_NEUTRAL: str = "neutral"

# --- Structure Break Constants ---
BREAK_BULLISH: str = "BULLISH_BREAK"
BREAK_BEARISH: str = "BEARISH_BREAK"
NO_BREAK: str = "NO_BREAK"

# --- Error/Status Constants ---
DATA_ERROR_MSG: str = "Data Error"
