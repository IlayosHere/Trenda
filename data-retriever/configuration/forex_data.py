FOREX_PAIRS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "GBPCAD",
    "EURJPY",
]

# 2. Define the timeframes you want to analyze
# Each timeframe maps to the Twelve Data interval code and
# the candle size in seconds (used to compute lookback windows)
TIMEFRAMES = {
    "1D": {"interval": "1day", "seconds": 24 * 60 * 60},
    "4H": {"interval": "4h", "seconds": 4 * 60 * 60},
    "1H": {"interval": "1h", "seconds": 60 * 60},
}

# 3. !! CRITICAL TUNING !!
# You MUST adjust 'distance' and 'prominence' for each timeframe.
# These values are just *examples* to get you started.
# Use the visual plotting method we discussed to find the right values.
ANALYSIS_PARAMS = {
    # timeframe: {lookback_candles, distance_filter, prominence_filter_in_pips}
    # (Note: prominence is in price units, e.g., 0.0010 for EURUSD)
    "1D": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~1 year
    "4H": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~1.5 months
    "1H": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~1 week
}
