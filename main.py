import time
import pandas as pd
from typing import List, Dict, Tuple, Optional, Any

# --- Import project modules ---
from config import ANALYSIS_PARAMS, FOREX_PAIRS, TIMEFRAMES
from data_analyzer import analyze_symbol
from data_fetcher import fetch_data
from mt5_connector import initialize_mt5, shutdown_mt5
from trend_analyzer import analyze_snake_trend, get_swing_points
from constants import (
    SwingPoint, DATA_ERROR_MSG
)
# Import the new display module
import display


def run_full_analysis() -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    """
    Orchestrates the analysis for ALL symbols and returns the final DataFrames.
    """
    trend_dashboard: Dict[str, Dict[str, str]] = {}
    high_dashboard: Dict[str, Dict[str, Optional[float]]] = {}
    low_dashboard: Dict[str, Dict[str, Optional[float]]] = {}

    display.print_status("\n--- 🏃‍♂️ Running Snake-Line Trend Analysis ---")
    
    for symbol in FOREX_PAIRS:
        trend_res, high_res, low_res = analyze_symbol(symbol)
        
        trend_dashboard[symbol] = trend_res
        high_dashboard[symbol] = high_res
        low_dashboard[symbol] = low_res

    try:
        trend_df = pd.DataFrame(trend_dashboard).T.reindex(columns=TIMEFRAMES.keys())
        high_df = pd.DataFrame(high_dashboard).T.reindex(columns=TIMEFRAMES.keys())
        low_df = pd.DataFrame(low_dashboard).T.reindex(columns=TIMEFRAMES.keys())
        
        return trend_df, high_df, low_df
        
    except Exception as e:
        display.print_error(f"Error creating final DataFrames: {e}")
        return None

def main():
    """
    Main entry point for the script.
    Handles initialization, execution, printing, and shutdown.
    """
    start_time = time.time()
    
    if not initialize_mt5():
        return # Exit if MT5 can't start

    try:
        results = run_full_analysis()
        end_time = time.time()
        
        display.print_completion(start_time, end_time)

        if results is not None:
            # Call the display module to handle all printing
            display.print_analysis_results(*results)
        else:
            display.print_error("Analysis could not be completed.")
            
    except Exception as e:
        display.print_error(f"An unexpected error occurred in main: {e}")
    finally:
        # 3. Always shut down MT5
        shutdown_mt5()
        display.print_shutdown(start_time, time.time())

# --- Run the bot ---
if __name__ == "__main__":
    main()
