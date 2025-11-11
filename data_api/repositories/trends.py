"""Data access helpers for trend and AOI related queries."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from psycopg2.extras import RealDictCursor

from ..db import get_connection
from ..logging_config import get_logger

log = get_logger(__name__)


TREND_QUERY = """
    SELECT
        fp.name AS symbol,
        tf.type AS timeframe,
        td.trend,
        td.high,
        td.low,
        to_char(td.last_updated AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS last_updated
    FROM
        trend_data td
    JOIN
        forex fp ON td.forex_id = fp.id
    JOIN
        timeframes tf ON td.timeframe_id = tf.id
    ORDER BY
        fp.name,
        CASE tf.type
            WHEN '1W' THEN 1
            WHEN '1D' THEN 2
            WHEN '4H' THEN 3
            WHEN '1H' THEN 4
            WHEN '30min' THEN 5
            WHEN '15min' THEN 6
            ELSE 99
        END;
"""


TREND_RANGE_QUERY = """
    SELECT
        td.high,
        td.low
    FROM trenda.trend_data td
    JOIN forex fp ON td.forex_id = fp.id
    JOIN timeframes tf ON td.timeframe_id = tf.id
    WHERE fp.name = %s AND tf.type = %s
"""


AOI_QUERY = """
    SELECT
        lower_bound,
        upper_bound
    FROM trenda.area_of_interest
    WHERE forex_id = (SELECT id FROM trenda.forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM trenda.timeframes WHERE type = %s)
    ORDER BY lower_bound ASC
"""


def fetch_all_trends() -> Optional[List[Dict[str, object]]]:
    """Return all trend rows or ``None`` if the database could not be queried."""

    try:
        with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(TREND_QUERY)
            records: Iterable[Dict[str, object]] = cursor.fetchall()
            payload = [dict(record) for record in records]
            log.info("Retrieved %d trend records", len(payload))
            return payload
    except Exception:  # pragma: no cover - operational errors logged
        log.exception("Failed to fetch trend data")
        return None


def fetch_aoi(symbol: str, timeframe: str) -> Optional[Dict[str, object]]:
    """Fetch AOI data for a symbol and timeframe."""

    try:
        with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(TREND_RANGE_QUERY, (symbol, timeframe))
            trend_row = cursor.fetchone()

            cursor.execute(AOI_QUERY, (symbol, timeframe))
            aoi_rows = cursor.fetchall()

        if trend_row is None and not aoi_rows:
            log.info("No AOI data found for symbol '%s' timeframe '%s'", symbol, timeframe)
            return None

        response: Dict[str, object] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "high": trend_row.get("high") if trend_row else None,
            "low": trend_row.get("low") if trend_row else None,
            "aois": [
                {
                    "lower_bound": row.get("lower_bound"),
                    "upper_bound": row.get("upper_bound"),
                }
                for row in aoi_rows
            ],
        }
        return response
    except Exception:  # pragma: no cover - operational errors logged
        log.exception("Failed to fetch AOI data for symbol '%s'", symbol)
        return None
