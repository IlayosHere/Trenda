import psycopg2
from typing import Dict, List, Optional, Tuple

from configuration import POSTGRES_DB
import utils.display as display


def get_db_connection():
    try:
        conn = psycopg2.connect(**POSTGRES_DB)
        cur = conn.cursor()
        cur.execute("SELECT current_database(), current_schema();")
        print("Connected to DB and schema:", cur.fetchone())
        return conn
    except psycopg2.OperationalError as e:
        display.print_error(f"DATABASE CONNECTION FAILED: {e}")
        return None


def update_trend_data(
    symbol: str, timeframe: str, trend: str, high: Optional[float], low: Optional[float]
) -> None:

    sql = """
    INSERT INTO trenda.trend_data (forex_id, timeframe_id, trend, high, low, last_updated)
    VALUES (
        (SELECT id FROM forex WHERE name = %s),
        (SELECT id FROM timeframes WHERE type = %s),
        %s, %s, %s, CURRENT_TIMESTAMP
    )
    ON CONFLICT (forex_id, timeframe_id) DO UPDATE SET
        trend = excluded.trend,
        high = excluded.high,
        low = excluded.low,
        last_updated = CURRENT_TIMESTAMP
    """
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not update trend for {symbol}/{timeframe}, DB connection failed."
        )
        return

    with conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (symbol, timeframe, trend, high, low))
            conn.commit()
        except Exception as e:
            display.print_error(
                f"Error during trend update for {symbol}/{timeframe}: {e}"
            )
            conn.rollback()  # Roll back the failed transaction


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
        (SELECT id FROM forex WHERE name = %s),
        (SELECT id FROM timeframes WHERE type = %s),
        %s, %s, CURRENT_TIMESTAMP
    )
    ON CONFLICT (forex_id, timeframe_id, lower_bound, upper_bound) DO UPDATE SET
        lower_bound = EXCLUDED.lower_bound,
        upper_bound = EXCLUDED.upper_bound,
        last_updated = CURRENT_TIMESTAMP
    """

    delete_all_sql = """
    DELETE FROM trenda.area_of_interest
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
    """

    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not store AOIs for {symbol}/{timeframe}, DB connection failed."
        )
        return

    with conn:
        try:
            with conn.cursor() as cursor:
                if not aois:
                    cursor.execute(delete_all_sql, (symbol, timeframe))
                    return

                bounds: List[Tuple[Optional[float], Optional[float]]] = []

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
                    bounds.append((lower, upper))

                placeholders = ", ".join(["(%s, %s)"] * len(bounds))
                delete_sql = f"""
                DELETE FROM trenda.area_of_interest
                WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
                  AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
                  AND (lower_bound, upper_bound) NOT IN ({placeholders})
                """

                params: List[object] = [symbol, timeframe]
                for lower, upper in bounds:
                    params.extend([lower, upper])

                cursor.execute(delete_sql, params)

            conn.commit()
        except Exception as e:
            display.print_error(
                f"Error while storing AOIs for {symbol}/{timeframe}: {e}"
            )
            conn.rollback()


def fetch_trend_levels(symbol: str, timeframe: str) -> Tuple[Optional[float], Optional[float]]:
    """Retrieve the stored high/low levels for a symbol/timeframe combination."""

    sql = """
    SELECT high, low
    FROM trenda.trend_data
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
    """

    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not fetch trend levels for {symbol}/{timeframe}, DB connection failed."
        )
        return None, None

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (symbol, timeframe))
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


