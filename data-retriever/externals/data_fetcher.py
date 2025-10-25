import pandas as pd
from typing import Optional, Dict, Any, Tuple
import time
from oandapyV20.exceptions import V20Error

# Import the OANDA handler instance and configuration
from .oanda_handler import oanda_handler
from configuration import OANDA_INSTRUMENTS, OANDA_GRANULARITIES
# Import strategy params for lookback (can be adjusted if needed)
from configuration import ANALYSIS_PARAMS

# Import utilities
from constants import DATA_ERROR_MSG
import utils.display as display
from utils.data_conversion import convert_candles


# --- Helper Function for a Single Fetch Attempt ---

def attempt_oanda_fetch(instrument: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not oanda_handler.is_connected():
        return None
    
    response = oanda_handler.get_candles(instrument, params)
    return response

def fetch_data(
    symbol: str, timeframe: str, lookback: int
) -> Optional[pd.DataFrame]:
    instrument = OANDA_INSTRUMENTS.get(symbol)
    granularity = OANDA_GRANULARITIES.get(timeframe)

    if not instrument or not granularity:
        display.print_error(f"Data Fetcher: Invalid symbol '{symbol}' or timeframe '{timeframe}' for OANDA.")
        return None

    fetch_count = min(lookback, 5000) # Respect OANDA's max limit
    params = {"count": fetch_count, "granularity": granularity, "price": "M"} # Midpoint candles

    max_retries = 3
    initial_delay_seconds = 2

    # 4. Retry Loop
    for attempt in range(max_retries):
        log_prefix = f"Fetch {symbol}/{timeframe} (Attempt {attempt + 1}/{max_retries})"
        try:
            # --- Make the fetch attempt ---
            response = attempt_oanda_fetch(instrument, params)

            # Check for immediate issues (connection unavailable, empty response)
            if response is None:
                display.print_error(f"{log_prefix}: Fetch attempt returned None. Check connection or previous V20Error.")

            elif "candles" not in response or not response["candles"]:
                display.print_status(f"  -> {log_prefix}: No candle data received from OANDA.")
                return None

            else:
                data = convert_candles(response["candles"])

                if data is None:
                    # Conversion failed (error logged inside converter)
                    display.print_error(f"{log_prefix}: Conversion failed. Aborting fetch.")
                    return None # Conversion failure is final

                return data # SUCCESS! Exit the function.

        # --- Handle Specific Errors for Retry ---
        except V20Error as e:
            error_message = str(e).lower()
            # Check if error type suggests retrying might help
            should_retry = (
                any(kw in error_message for kw in ["rate limit", "too many requests", "500", "502", "503", "504", "service unavailable", "internal server error"])
            )

            display.print_error(f"{log_prefix}: OANDA API Error: {e}")
            if should_retry and attempt < max_retries - 1:
                delay = initial_delay_seconds * (2 ** attempt) # Exponential backoff
                display.print_status(f"   -> Retrying fetch in {delay}s...")
                time.sleep(delay)
                continue # Go to the next attempt
            else:
                display.print_error(f"   -> Non-retryable error or max retries reached. Aborting fetch.")
                return None # Give up

        except ConnectionError as e:
            # Network-level errors are usually worth retrying
            display.print_error(f"{log_prefix}: Network Connection Error: {e}")
            if attempt < max_retries - 1:
                delay = initial_delay_seconds * (2 ** (attempt + 1)) # Longer delay for connection issues
                display.print_status(f"   -> Retrying fetch in {delay}s...")
                time.sleep(delay)
                continue
            else:
                display.print_error(f"   -> Max retries reached after connection error. Aborting fetch.")
                return None

        # --- Handle Unexpected Errors ---
        except Exception as e:
            display.print_error(f"{log_prefix}: Unexpected Error: {e}")
            # Optionally retry unexpected errors once or twice
            if attempt < max_retries - 1:
                delay = initial_delay_seconds * (2 ** attempt)
                display.print_status(f"   -> Retrying fetch after unexpected error in {delay}s...")
                time.sleep(delay)
                continue
            else:
                display.print_error(f"   -> Max retries reached after unexpected error. Aborting fetch.")
                return None

    # --- Fallback if loop completes without success ---
    display.print_error(f"Data Fetcher: Failed fetch for {symbol}/{timeframe} after all retries.")
    return None