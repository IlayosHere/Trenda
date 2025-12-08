from typing import Any, Mapping, Optional, Sequence

import utils.display as display

from .db import execute_transaction, validate_nullable_float, validate_symbol
from .helpers import required_trend, value_from_candle
from .queries import INSERT_ENTRY_CANDLE, INSERT_ENTRY_SIGNAL, INSERT_TREND_SNAPSHOT


def store_entry_signal(
    symbol: str,
    trend_snapshot: Mapping[str, Optional[str]],
    aoi_high: float,
    aoi_low: float,
    signal_time,
    candles: Sequence[Any],
    trade_quality: float,
) -> Optional[int]:
    """Persist an entry signal and its supporting candles."""
    if not validate_symbol(symbol):
        return None
    if not isinstance(trade_quality, (int, float)):
        display.print_error("DB_VALIDATION: trade_quality must be numeric")
        return None
    if not validate_nullable_float(aoi_high, "aoi_high") or not validate_nullable_float(
        aoi_low, "aoi_low"
    ):
        return None

    try:
        trend_values = (
            required_trend(trend_snapshot, "4H"),
            required_trend(trend_snapshot, "1D"),
            required_trend(trend_snapshot, "1W"),
        )
    except (TypeError, ValueError) as exc:
        display.print_error(f"DB_VALIDATION: invalid trend snapshot - {exc}")
        return None

    def _validate_candle_value(value: Any, field: str) -> Optional[float]:
        if not isinstance(value, (int, float)):
            display.print_error(f"DB_VALIDATION: candle {field} must be numeric")
            return None
        return float(value)

    def _persist(cursor):
        cursor.execute(INSERT_TREND_SNAPSHOT, trend_values)
        signal_trend_id = cursor.fetchone()[0]

        cursor.execute(
            INSERT_ENTRY_SIGNAL,
            (symbol, signal_time, signal_trend_id, aoi_high, aoi_low, trade_quality),
        )
        signal_id = cursor.fetchone()[0]

        candle_rows = []
        for idx, candle in enumerate(candles, start=1):
            candle_row = (
                signal_id,
                idx,
                _validate_candle_value(value_from_candle(candle, "high"), "high"),
                _validate_candle_value(value_from_candle(candle, "low"), "low"),
                _validate_candle_value(value_from_candle(candle, "open"), "open"),
                _validate_candle_value(value_from_candle(candle, "close"), "close"),
            )
            if any(value is None for value in candle_row[2:]):
                return None
            candle_rows.append(candle_row)

        cursor.executemany(INSERT_ENTRY_CANDLE, candle_rows)
        return signal_id

    return execute_transaction(_persist, context="store_entry_signal")
