from typing import Tuple

# --- Type Definitions ---
# (index, price, 'H'/'L')
SwingPoint = Tuple[int, float, str]

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