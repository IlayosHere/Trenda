
import pandas as pd
from datetime import datetime, timezone

# Mock DataFrame acting as candles
# Simulating 1H candles in UTC
data = {
    "time": [
        datetime(2023, 10, 27, 7, 0, 0),  # 07:00 UTC
        datetime(2023, 10, 27, 8, 0, 0),  # 08:00 UTC (10:00 UTC+2)
        datetime(2023, 10, 27, 9, 0, 0),  # 09:00 UTC
    ],
    "open": [1.0, 1.1, 1.2],
    "close": [1.1, 1.2, 1.3]
}
df = pd.DataFrame(data)

# Signal time: 10:00 UTC+2 => 08:00 UTC
signal_time_str = "2023-10-27 10:00:00+02:00"
signal_time = pd.to_datetime(signal_time_str, utc=True)
print(f"Signal Time (UTC): {signal_time}")

# Mock find_index_by_time logic from candle_store.py
# Normalizes target_time to naive UTC if needed
if signal_time.tzinfo is not None:
    target_utc = signal_time.replace(tzinfo=None) if signal_time.utcoffset().total_seconds() == 0 else signal_time.astimezone(timezone.utc).replace(tzinfo=None)
else:
    target_utc = signal_time

print(f"Target UTC (Naive): {target_utc}")

# Finding index
# Assuming candle times are naive (as per candle_store.py default handling for MT5 data)
matches = df[df["time"] == target_utc]

if not matches.empty:
    idx = matches.index[0]
    print(f"Found candle at index: {idx}")
    print(f"Candle Time: {df.loc[idx, 'time']}")
    if df.loc[idx, 'time'] == target_utc:
        print("VERIFIED: Fetches candle starting at signal time.")
    else:
        print("FAILED: Fetched wrong candle.")
else:
    print("FAILED: Candle not found.")
