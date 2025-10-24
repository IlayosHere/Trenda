from typing import Dict, Optional, Tuple

from config import ANALYSIS_PARAMS, TIMEFRAMES
from constants import DATA_ERROR_MSG
from data_fetcher import fetch_data
import display
from trend_analyzer import analyze_snake_trend, get_swing_points


def analyze_symbol(symbol: str) -> Tuple[Dict[str, str], Dict[str, Optional[float]], Dict[str, Optional[float]]]:
    """
    Analyzes a single symbol across all configured timeframes.
    
    Args:
        symbol (str): The symbol to analyze (e.g., "EURUSD").

    Returns:
        A tuple containing three dictionaries for this symbol's results:
        (trend_results, high_results, low_results)
    """
    display.print_status(f"Analyzing {symbol}...")
    
    trend_results: Dict[str, str] = {}
    high_results: Dict[str, Optional[float]] = {}
    low_results: Dict[str, Optional[float]] = {}

    for tf_name, tf_mt5 in TIMEFRAMES.items():
        params = ANALYSIS_PARAMS[tf_name]
        df = fetch_data(symbol, tf_mt5, params["lookback"])
        
        if df is None:
            trend_results[tf_name] = DATA_ERROR_MSG
            high_results[tf_name] = None
            low_results[tf_name] = None
            continue
            
        prices = df['close'].values
        swings = get_swing_points(prices, params["distance"], params["prominence"])
        trend, struct_high, struct_low = analyze_snake_trend(swings)

        trend_results[tf_name] = trend
        high_results[tf_name] = struct_high[1] if struct_high else None
        low_results[tf_name] = struct_low[1] if struct_low else None
    
    return trend_results, high_results, low_results