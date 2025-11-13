from typing import Optional

import externals.db_handler as db_handler


def determine_trend(symbol: str, timeframe: str) -> Optional[str]:
    """Wrapper around the DB trend provider for testability."""

    result = db_handler.fetch_trend_bias(symbol, timeframe)
    return result[0] if result else None
