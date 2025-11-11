"""AOI analysis configuration constants."""

AOI_SOURCE_TIMEFRAME = "4H"
TARGET_TIMEFRAME = "4H"

# Core rules
AOI_MIN_TOUCHES = 3
AOI_MIN_RANGE_PIPS = 30
AOI_MIN_SWING_GAP_BARS = 3          # temporal spacing between swing touches (1H bars)
AOI_OVERLAP_TOLERANCE_PIPS = 2.0    # merge/overlap tolerance
AOI_MAX_AGE_DAYS = 2
AOI_MAX_AGE_BARS = int((AOI_MAX_AGE_DAYS * 24) / 4)  # convert to 4H bars
AOI_MAX_ZONES_PER_SYMBOL = 3        # keep top 3 overall (tradable bias via weighting)

# Dynamic sizing
AOI_MIN_HEIGHT_RATIO = 0.05          # 5% of 4H range
AOI_MIN_HEIGHT_PIPS_FLOOR = 8        # absolute minimum AOI height
AOI_MAX_HEIGHT_RATIO = 0.15          # 15% of 4H range
AOI_MAX_HEIGHT_MIN_PIPS = 10
AOI_MAX_HEIGHT_MAX_PIPS = 20

# Dynamic bound tolerance (to catch wicks/fakeouts slightly outside 4H bounds)
AOI_BOUND_TOLERANCE_RATIO = 0.05   # ±5% of 4H range

# Trend alignment weighting (bias for tradable side)
AOI_ALIGNMENT_WEIGHT = 1.25         # 25% bonus for trend-aligned AOIs

__all__ = [
    "AOI_SOURCE_TIMEFRAME",
    "TARGET_TIMEFRAME",
    "AOI_MIN_TOUCHES",
    "AOI_MIN_RANGE_PIPS",
    "AOI_MIN_SWING_GAP_BARS",
    "AOI_OVERLAP_TOLERANCE_PIPS",
    "AOI_MAX_AGE_BARS",
    "AOI_MAX_ZONES_PER_SYMBOL",
    "AOI_MIN_HEIGHT_RATIO",
    "AOI_MIN_HEIGHT_PIPS_FLOOR",
    "AOI_MAX_HEIGHT_RATIO",
    "AOI_MAX_HEIGHT_MIN_PIPS",
    "AOI_MAX_HEIGHT_MAX_PIPS",
    "AOI_BOUND_TOLERANCE_RATIO",
    "AOI_ALIGNMENT_WEIGHT",
]
