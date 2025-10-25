import pandas as pd
from typing import Optional, List, Dict, Any
# Import display for logging errors during conversion
import utils.display as display

def convert_candles(candles: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
    if not candles:
        display.print_warning("Data Conversion: Received empty candle list.")
        return None

    data = []
    price_type = 'mid' # Use 'mid', 'bid', or 'ask' based on OANDA candle data required

    for candle in candles:
        if not candle.get('complete', False):
            continue
        if price_type not in candle:
            display.print_error(f"Data Conversion Error: Price type '{price_type}' not found in candle. Available: {list(candle.keys())}. Time: {candle.get('time')}")
            continue

        try:
            data.append(format_candle_data(candle, price_type))
        except KeyError as e:
            display.print_error(f"Data Conversion Error: Missing key {e} in candle. Candle: {candle}")
            continue
        except (ValueError, TypeError) as e:
             display.print_error(f"Data Conversion Error: Could not convert value in candle. Error: {e}. Candle: {candle}")
             continue

    if not data:
        display.print_warning("Data Conversion: No valid/complete candles found after filtering.")
        return None

    try:
        convert_by_panda(data)
    except Exception as e:
        display.print_error(f"Data Conversion Error: Failed creating DataFrame: {e}")
        return None
    
def format_candle_data(candle, price_type):
    ohlc = candle[price_type]
    if not all(k in ohlc for k in ('o', 'h', 'l', 'c')):
            display.print_error(f"Data Conversion Error: Missing OHLC key in '{price_type}' dict. Candle: {candle}")
            return None
    
    return {
        "time": candle["time"], # Keep as string for now, pandas handles conversion
        "open": float(ohlc["o"]),
        "high": float(ohlc["h"]),
        "low": float(ohlc["l"]),
        "close": float(ohlc["c"]),
        "volume": int(candle["volume"])
    }

def convert_by_panda(data):
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df.set_index("time", inplace=True)
    return df