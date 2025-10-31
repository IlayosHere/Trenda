import MetaTrader5 as mt5

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
TIMEFRAMES = {
    "1W": mt5.TIMEFRAME_W1,
    "1D": mt5.TIMEFRAME_D1,
    "4H": mt5.TIMEFRAME_H4,
    "1H": mt5.TIMEFRAME_H1,
    "30min": mt5.TIMEFRAME_M30,
}

# 3. !! CRITICAL TUNING !!
# You MUST adjust 'distance' and 'prominence' for each timeframe.
# These values are just *examples* to get you started.
# Use the visual plotting method we discussed to find the right values.
ANALYSIS_PARAMS = {
    # timeframe: {lookback_candles, distance_filter, prominence_filter_in_pips}
    # (Note: prominence is in price units, e.g., 0.0010 for EURUSD)
    "1W": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~2 years
    "1D": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~1 year
    "4H": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~1.5 months
    "1H": {"lookback": 100, "distance": 1, "prominence": 0.0004},  # ~1 week
    "30min": {"lookback": 200, "distance": 2, "prominence": 0.0003},
}
