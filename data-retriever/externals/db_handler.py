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
    source_range_pips: float,
) -> None:
    """Sync AOI zones for a forex pair/timeframe combination."""

    existing_sql = """
    SELECT id, lower_bound, upper_bound
    FROM trenda.area_of_interest
    WHERE forex_id = (SELECT id FROM forex WHERE name = %s)
      AND timeframe_id = (SELECT id FROM timeframes WHERE type = %s)
    """

    update_sql = """
    UPDATE trenda.area_of_interest
    SET lower_bound = %s,
        upper_bound = %s,
        touches = %s,
        height_pips = %s,
        source_range_pips = %s,
        last_updated = CURRENT_TIMESTAMP
    WHERE id = %s
    """

    insert_sql = """
    INSERT INTO trenda.area_of_interest
        (forex_id, timeframe_id, lower_bound, upper_bound, touches, height_pips, source_range_pips, last_updated)
    VALUES (
        (SELECT id FROM forex WHERE name = %s),
        (SELECT id FROM timeframes WHERE type = %s),
        %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
    )
    RETURNING id
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
                cursor.execute(existing_sql, (symbol, timeframe))
                existing_rows = cursor.fetchall()

                def _key(lower: Optional[float], upper: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
                    if lower is None and upper is None:
                        return (None, None)
                    return (
                        round(lower, 8) if lower is not None else None,
                        round(upper, 8) if upper is not None else None,
                    )

                existing_map = {
                    _key(row[1], row[2]): row[0] for row in existing_rows
                }
                seen_ids = set()

                for aoi in aois:
                    lower = aoi.get("lower_bound")
                    upper = aoi.get("upper_bound")
                    touches = aoi.get("touches")
                    height_pips = aoi.get("height_pips")
                    key = _key(lower, upper)

                    existing_id = existing_map.get(key)
                    if existing_id:
                        cursor.execute(
                            update_sql,
                            (
                                lower,
                                upper,
                                touches,
                                height_pips,
                                source_range_pips,
                                existing_id,
                            ),
                        )
                        seen_ids.add(existing_id)
                    else:
                        cursor.execute(
                            insert_sql,
                            (
                                symbol,
                                timeframe,
                                lower,
                                upper,
                                touches,
                                height_pips,
                                source_range_pips,
                            ),
                        )
                        new_id = cursor.fetchone()[0]
                        seen_ids.add(new_id)

                if existing_rows:
                    delete_sql = """
                    DELETE FROM trenda.area_of_interest
                    WHERE id = ANY(%s)
                    """
                    leftover_ids = [row[0] for row in existing_rows if row[0] not in seen_ids]
                    if leftover_ids:
                        cursor.execute(delete_sql, (leftover_ids,))

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


