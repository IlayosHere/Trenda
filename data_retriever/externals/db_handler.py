"""PostgreSQL helpers for persisting trend and AOI analysis outputs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Generator, List, Optional, Tuple

import psycopg2
from psycopg2.extensions import connection as PgConnection

from data_retriever.configuration import POSTGRES_DB
from data_retriever.utils import display


@contextmanager
def get_db_connection() -> Generator[Optional[PgConnection], None, None]:
    """Yield a database connection and ensure it is closed."""
    try:
        conn = psycopg2.connect(**POSTGRES_DB)
        yield conn
    except psycopg2.OperationalError as exc:
        display.print_error(f"DATABASE CONNECTION FAILED: {exc}")
        yield None
    finally:
        if 'conn' in locals() and conn:
            conn.close()


def update_trend_data(
    symbol: str, timeframe: str, trend: str, high: Optional[float], low: Optional[float]
) -> None:
    sql = """
    INSERT INTO trenda.trend_data (forex_id, timeframe_id, trend, high, low, last_updated)
    VALUES (
        (SELECT id FROM trenda.forex WHERE name = %s),
        (SELECT id FROM trenda.timeframes WHERE type = %s),
        %s, %s, %s, CURRENT_TIMESTAMP
    )
    ON CONFLICT (forex_id, timeframe_id) DO UPDATE SET
        trend = excluded.trend,
        high = excluded.high,
        low = excluded.low,
        last_updated = CURRENT_TIMESTAMP
    """

    with get_db_connection() as conn:
        if conn is None:
            display.print_error(
                f"Could not update trend for {symbol}/{timeframe}, DB connection failed."
            )
            return

        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (symbol, timeframe, trend, high, low))
            conn.commit()
        except Exception as exc:
            display.print_error(
                f"Error during trend update for {symbol}/{timeframe}: {exc}"
            )
            conn.rollback()


def store_aois(
    symbol: str,
    timeframe: str,
    aois: List[Dict[str, float]],
) -> None:
    """Sync AOI zones for a forex pair/timeframe combination."""

    upsert_sql = """
    INSERT INTO trenda.area_of_interest
        (forex_id, timeframe_id, lower_bound, upper_bound, last_updated)
    VALUES (
        (SELECT id FROM trenda.forex WHERE name = %s),
        (SELECT id FROM trenda.timeframes WHERE type = %s),
        %s, %s, CURRENT_TIMESTAMP
    )
    """

    delete_all_sql = """
    DELETE FROM trenda.area_of_interest
    WHERE forex_id = (SELECT id FROM trenda.forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM trenda.timeframes WHERE type = %s)
    """

    with get_db_connection() as conn:
        if conn is None:
            display.print_error(
                f"Could not store AOIs for {symbol}/{timeframe}, DB connection failed."
            )
            return

        try:
            with conn.cursor() as cursor:
                cursor.execute(delete_all_sql, (symbol, timeframe))

                for aoi in aois:
                    lower = aoi.get("lower_bound")
                    upper = aoi.get("upper_bound")
                    cursor.execute(
                        upsert_sql,
                        (
                            symbol,
                            timeframe,
                            lower,
                            upper,
                        ),
                    )

            conn.commit()
        except Exception as exc:
            display.print_error(
                f"Error while storing AOIs for {symbol}/{timeframe}: {exc}"
            )
            conn.rollback()


def fetch_trend_bias(symbol: str, timeframe: str) -> Optional[str]:
    sql = """
    SELECT trend
    FROM trenda.trend_data
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
    """

    with get_db_connection() as conn:
        if conn is None:
            display.print_error(
                f"Could not fetch trend levels for {symbol}/{timeframe}, DB connection failed."
            )
            return None

        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (symbol, timeframe))
                row = cursor.fetchone()
        except Exception as exc:
            display.print_error(
                f"Error while fetching trend for {symbol}/{timeframe}: {exc}"
            )
            return None

    if not row:
        return None

    return row[0]


def fetch_trend_levels(symbol: str, timeframe: str) -> Tuple[Optional[float], Optional[float]]:
    """Retrieve the stored high/low levels for a symbol/timeframe combination."""

    sql = """
    SELECT high, low
    FROM trenda.trend_data
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
    """

    with get_db_connection() as conn:
        if conn is None:
            display.print_error(
                f"Could not fetch trend levels for {symbol}/{timeframe}, DB connection failed."
            )
            return None, None

        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (symbol, timeframe))
                row = cursor.fetchone()
        except Exception as exc:
            display.print_error(
                f"Error while fetching trend levels for {symbol}/{timeframe}: {exc}"
            )
            return None, None

    if not row:
        return None, None

    high, low = row
    return (
        float(high) if high is not None else None,
        float(low) if low is not None else None,
    )
