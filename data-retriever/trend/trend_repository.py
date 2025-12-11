from typing import Optional, Tuple

import utils.display as display

from models import TrendDirection
from database.executor import DBExecutor
from database.queries import FETCH_TREND_BIAS, FETCH_TREND_LEVELS, UPDATE_TREND_DATA
from database.validation import DBValidator


def update_trend_data(
    symbol: str, timeframe: str, trend: TrendDirection, high: Optional[float], low: Optional[float]
) -> None:
    normalized_symbol = DBValidator.validate_symbol(symbol)
    normalized_timeframe = DBValidator.validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return
    if not trend or not isinstance(trend, TrendDirection):
        display.print_error("DB_VALIDATION: trend must be provided as a TrendDirection")
        return
    if not DBValidator.validate_nullable_float(high, "high") or not DBValidator.validate_nullable_float(low, "low"):
        return

    DBExecutor.execute_non_query(
        UPDATE_TREND_DATA,
        (normalized_symbol, normalized_timeframe, trend.value, high, low),
        context="update_trend_data",
    )


def fetch_trend_bias(symbol: str, timeframe: str) -> Optional[TrendDirection]:
    normalized_symbol = DBValidator.validate_symbol(symbol)
    normalized_timeframe = DBValidator.validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return None

    row = DBExecutor.fetch_one(
        FETCH_TREND_BIAS,
        (normalized_symbol, normalized_timeframe),
        context="fetch_trend_bias",
    )

    if not row:
        return None

    return TrendDirection.from_raw(row[0])


def fetch_trend_levels(symbol: str, timeframe: str) -> Tuple[Optional[float], Optional[float]]:
    """Retrieve the stored high/low levels for a symbol/timeframe combination."""
    normalized_symbol = DBValidator.validate_symbol(symbol)
    normalized_timeframe = DBValidator.validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return None, None

    row = DBExecutor.fetch_one(
        FETCH_TREND_LEVELS,
        (normalized_symbol, normalized_timeframe),
        context="fetch_trend_levels",
    )

    if not row:
        return None, None

    high, low = row
    return (
        float(high) if high is not None else None,
        float(low) if low is not None else None,
    )
