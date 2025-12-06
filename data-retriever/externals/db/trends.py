from typing import Optional, Tuple

import utils.display as display

from .connection import get_db_connection
from .queries import FETCH_TREND_BIAS, FETCH_TREND_LEVELS, UPDATE_TREND_DATA


def update_trend_data(
    symbol: str, timeframe: str, trend: str, high: Optional[float], low: Optional[float]
) -> None:
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not update trend for {symbol}/{timeframe}, DB connection failed."
        )
        return

    with conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    UPDATE_TREND_DATA, (symbol, timeframe, trend, high, low)
                )
            conn.commit()
        except Exception as e:
            display.print_error(
                f"Error during trend update for {symbol}/{timeframe}: {e}"
            )
            conn.rollback()  # Roll back the failed transaction


def fetch_trend_bias(symbol: str, timeframe: str) -> Optional[str]:
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not fetch trend levels for {symbol}/{timeframe}, DB connection failed."
        )
        return None

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(FETCH_TREND_BIAS, (symbol, timeframe))
                row = cursor.fetchone()

        if not row:
            return None

        trend_value = row[0]
        return trend_value
    except Exception as e:
        display.print_error(
            f"Error while fetching trend for {symbol}/{timeframe}: {e}"
        )
        return None


def fetch_trend_levels(symbol: str, timeframe: str) -> Tuple[Optional[float], Optional[float]]:
    """Retrieve the stored high/low levels for a symbol/timeframe combination."""
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not fetch trend levels for {symbol}/{timeframe}, DB connection failed."
        )
        return None, None

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(FETCH_TREND_LEVELS, (symbol, timeframe))
                row = cursor.fetchone()

        if not row:
            return None, None

        high, low = row
        return (
            float(high) if high is not None else None,
            float(low) if low is not None else None,
        )
    except Exception as e:
        display.print_error(
            f"Error while fetching trend levels for {symbol}/{timeframe}: {e}"
        )
        return None, None
