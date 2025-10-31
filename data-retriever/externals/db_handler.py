import psycopg2
from typing import Dict, List, Optional

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
    source_range_pips: float,
) -> None:
    """Replace AOI zones for a forex pair/timeframe combination."""

    delete_sql = """
    DELETE FROM trenda.areas_of_interest
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
    """

    insert_sql = """
    INSERT INTO trenda.areas_of_interest
        (forex_id, timeframe_id, lower_bound, upper_bound, touches, height_pips, source_range_pips, last_updated)
    VALUES (
        (SELECT id FROM forex WHERE name = %s),
        (SELECT id FROM timeframes WHERE type = %s),
        %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
    )
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
                cursor.execute(delete_sql, (symbol, timeframe))

                for aoi in aois:
                    cursor.execute(
                        insert_sql,
                        (
                            symbol,
                            timeframe,
                            aoi.get("lower_bound"),
                            aoi.get("upper_bound"),
                            aoi.get("touches"),
                            aoi.get("height_pips"),
                            source_range_pips,
                        ),
                    )
            conn.commit()
        except Exception as e:
            display.print_error(
                f"Error while storing AOIs for {symbol}/{timeframe}: {e}"
            )
            conn.rollback()


