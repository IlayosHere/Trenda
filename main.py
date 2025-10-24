# --- IMPORTS ---
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from scipy.signal import find_peaks
import time
from typing import List, Dict, Tuple, Optional, Any

from config import ANALYSIS_PARAMS, FOREX_PAIRS, TIMEFRAMES
from data_fetcher import fetch_data
from mt5_connector import initialize_mt5, shutdown_mt5
from trend_analyzer import analyze_snake_trend, get_swing_points

# --- MAIN EXECUTION ---

def analyze_symbol(symbol: str) -> Tuple[Dict[str, str], Dict[str, Optional[float]], Dict[str, Optional[float]]]:
    print(f"Analyzing {symbol}...")
    
    trend_results: Dict[str, str] = {}
    high_results: Dict[str, Optional[float]] = {}
    low_results: Dict[str, Optional[float]] = {}

    for tf_name, tf_mt5 in TIMEFRAMES.items():
        params = ANALYSIS_PARAMS[tf_name]
        fetched_data = fetch_data(symbol, tf_mt5, params["lookback"])
        
        if fetched_data is None:
            trend_results[tf_name] = "Data Error"
            high_results[tf_name] = None
            low_results[tf_name] = None
            continue
            
        prices = fetched_data['close'].values
        swings = get_swing_points(prices, params["distance"], params["prominence"])
        trend, struct_high, struct_low = analyze_snake_trend(swings)
        trend_results[tf_name] = trend
        high_results[tf_name] = struct_high[1] if struct_high else None
        low_results[tf_name] = struct_low[1] if struct_low else None
    
    return trend_results, high_results, low_results


def run_full_analysis() -> Optional[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
    trend_dashboard: Dict[str, Dict[str, str]] = {}
    high_dashboard: Dict[str, Dict[str, Optional[float]]] = {}
    low_dashboard: Dict[str, Dict[str, Optional[float]]] = {}

    print("\n--- 🏃‍♂️ Running Snake-Line Trend Analysis ---")
    
    for symbol in FOREX_PAIRS:
        trend_res, high_res, low_res = analyze_symbol(symbol)
        
        trend_dashboard[symbol] = trend_res
        high_dashboard[symbol] = high_res
        low_dashboard[symbol] = low_res

    # 4. Create Final DataFrames
    try:
        trend_df = pd.DataFrame(trend_dashboard).T.reindex(columns=TIMEFRAMES.keys())
        high_df = pd.DataFrame(high_dashboard).T.reindex(columns=TIMEFRAMES.keys())
        low_df = pd.DataFrame(low_dashboard).T.reindex(columns=TIMEFRAMES.keys())
        
        return trend_df, high_df, low_df
        
    except Exception as e:
        print(f"Error creating final DataFrames: {e}")
        return None


def main():
    start_time = time.time()
    
    if not initialize_mt5():
        return # Exit if MT5 can't start

    try:
        results = run_full_analysis()
        
        print(f"\n--- ✅ Analysis Complete (Took {time.time() - start_time:.2f}s) ---")

        # 2. Check if analysis was successful and PRINT results
        if results is not None:
            trend_df, high_df, low_df = results # Unpack the 3 DataFrames
            
            print("\n" + "="*45)
            print("--- 📊 Snake-Line Trend Analysis Results ---")
            print("="*45)
            print(trend_df)
            
            print("\n" + "="*45)
            print("--- 📈 Confirmed Structural HIGH Prices ---")
            print("="*45)
            # Use to_string() for better formatting of None/NaN
            print(high_df.to_string(float_format="%.5f")) 
            
            print("\n" + "="*45)
            print("--- 📉 Confirmed Structural LOW Prices ---")
            print("="*45)
            print(low_df.to_string(float_format="%.5f"))
            
        else:
            print("\n--- ⚠️ Analysis could not be completed. ---")
            
    except Exception as e:
        print(f"\n--- ❌ An unexpected error occurred in main: {e} ---")
    finally:
        # 3. Always shut down MT5
        shutdown_mt5()
        print(f"\nTotal execution time (including shutdown): {time.time() - start_time:.2f}s")

# --- Run the bot ---
if __name__ == "__main__":
    main()