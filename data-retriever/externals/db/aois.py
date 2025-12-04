from typing import Dict, List, Optional

import utils.display as display

from .connection import get_db_connection
from .queries import CLEAR_AOIS, FETCH_TRADABLE_AOIS, UPSERT_AOIS


def clear_aois(symbol: str, timeframe: str):
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not store AOIs for {symbol}/{timeframe}, DB connection failed."
        )
        return

    with conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(CLEAR_AOIS, (symbol, timeframe))
                conn.commit()
        except Exception as e:
            display.print_error(
                f"Error while storing AOIs for {symbol}/{timeframe}: {e}"
            )
            conn.rollback()


def store_aois(
    symbol: str,
    timeframe: str,
    aois: List[Dict[str, float]],
) -> None:
    """Sync AOI zones for a forex pair/timeframe combination."""
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not store AOIs for {symbol}/{timeframe}, DB connection failed."
        )
        return

    with conn:
        try:
            with conn.cursor() as cursor:
                for aoi in aois:
                    lower = aoi.get("lower_bound")
                    upper = aoi.get("upper_bound")
                    type = aoi.get("type")
                    cursor.execute(
                        UPSERT_AOIS,
                        (
                            symbol,
                            timeframe,
                            lower,
                            upper,
                            type
                        ),
                    )

            conn.commit()
        except Exception as e:
            display.print_error(
                f"Error while storing AOIs for {symbol}/{timeframe}: {e}"
            )
            conn.rollback()


def fetch_tradable_aois(symbol: str) -> List[Dict[str, Optional[float]]]:
    conn = get_db_connection()
    if not conn:
        display.print_error(
            f"Could not fetch AOIs for {symbol}, DB connection failed."
        )
        return []

    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(FETCH_TRADABLE_AOIS, (symbol,))
                rows = cursor.fetchall()

        return [
            {"lower_bound": float(row[0]) if row[0] is not None else None,
             "upper_bound": float(row[1]) if row[1] is not None else None}
            for row in rows
        ]
    except Exception as e:
        display.print_error(
            f"Error while fetching AOIs for {symbol}: {e}"
        )
        return []
