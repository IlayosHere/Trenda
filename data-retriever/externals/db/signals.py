from typing import Any, Mapping, Optional, Sequence

import utils.display as display

from .connection import get_db_connection
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

    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not store entry signal for {symbol}, DB connection failed."
        )
        return None

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    INSERT_TREND_SNAPSHOT,
                    (
                        required_trend(trend_snapshot, "4H"),
                        required_trend(trend_snapshot, "1D"),
                        required_trend(trend_snapshot, "1W"),
                    ),
                )
                signal_trend_id = cursor.fetchone()[0]

                cursor.execute(
                    INSERT_ENTRY_SIGNAL,
                    (symbol, signal_time, signal_trend_id, aoi_high, aoi_low, trade_quality),
                )
                signal_id = cursor.fetchone()[0]

                candle_rows = []
                for idx, candle in enumerate(candles, start=1):
                    candle_rows.append(
                        (
                            signal_id,
                            idx,
                            value_from_candle(candle, "high"),
                            value_from_candle(candle, "low"),
                            value_from_candle(candle, "open"),
                            value_from_candle(candle, "close"),
                        )
                    )

                cursor.executemany(INSERT_ENTRY_CANDLE, candle_rows)

            conn.commit()
            return signal_id
    except Exception as e:
        display.print_error(
            f"Error while storing entry signal for {symbol}: {e}"
        )
        conn.rollback()
        return None
