from typing import Optional

import externals.db_handler as db_handler


def get_overall_trend(timeframes: list[str, str], symbol: str) -> Optional[str]:
    trend_values = [ get_trend_by_timeframe(symbol, tf) for tf in timeframes ]
    
    if (trend_values[0]["trend"] == trend_values[1]["trend"] 
        or trend_values[1]["trend"] == trend_values[2]["trend"]):
        return trend_values[1]["trend"]
    
    return None
    
def get_trend_by_timeframe(symbol: str, timeframe: str) -> Optional[str]:
    """Wrapper around the DB trend provider for testability."""

    result = db_handler.fetch_trend_bias(symbol, timeframe)
    return {
       "trend": result,
       "timeframe": timeframe
    }
