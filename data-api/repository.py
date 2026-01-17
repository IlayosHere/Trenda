from typing import Optional, List, Dict, Any

from psycopg2.extras import RealDictCursor  # To get results as dictionaries
from dotenv import load_dotenv

from db import (
    fetch_all,
    fetch_one,
    validate_nullable_float,
    validate_symbol,
    validate_timeframe,
)

# --- Load Environment Variables ---
# Ensure environment variables are loaded if this module is imported early
load_dotenv()

from logger import get_logger

# --- Setup Logging ---
logger = get_logger(__name__)

# --- Data Fetching ---

def fetch_all_trend_data() -> Optional[List[Dict[str, Any]]]:
    sql = """
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
        -- Define a specific order for timeframes
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
    results = fetch_all(
        sql,
        cursor_factory=RealDictCursor,
        context="fetch_all_trend_data",
    )
    if results is None:
        logger.error("API Repo: Database query error while fetching trend data")
        return None

    logger.info(f"API Repo: Retrieved {len(results)} records.")
    return results


def fetch_aoi_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch AOI data along with trend levels for a specific symbol/timeframe."""
    VALIDATED_TIMEFRAME = "4H"
    normalized_symbol = validate_symbol(symbol)
    if not normalized_symbol:
        logger.error("API Repo: Invalid symbol provided for AOI lookup")
        return None

    trend_sql = """
        SELECT
            td.high,
            td.low
        FROM trenda.trend_data td
        JOIN forex fp ON td.forex_id = fp.id
        JOIN timeframes tf ON td.timeframe_id = tf.id
        WHERE fp.name = %s AND tf.type = %s
    """

    aoi_sql = """
        SELECT
            lower_bound,
            upper_bound
        FROM trenda.area_of_interest
        WHERE forex_id = (SELECT id FROM trenda.forex WHERE name = %s)
        ORDER BY lower_bound ASC
    """

    normalized_timeframe = validate_timeframe(VALIDATED_TIMEFRAME)
    if not normalized_timeframe:
        return None

    response: Dict[str, Any] = {
        "symbol": normalized_symbol,
        "low": None,
        "high": None,
        "aois": [],
    }

    trend_row = fetch_one(
        trend_sql,
        (normalized_symbol, normalized_timeframe),
        cursor_factory=RealDictCursor,
        context="fetch_aoi_trend",
    )

    if trend_row:
        high = trend_row.get("high")
        low = trend_row.get("low")
        if validate_nullable_float(high, "high") and validate_nullable_float(low, "low"):
            response["high"] = float(high) if high is not None else None
            response["low"] = float(low) if low is not None else None
        else:
            return None

    aoi_rows = fetch_all(
        aoi_sql,
        (normalized_symbol,),
        cursor_factory=RealDictCursor,
        context="fetch_aoi_rows",
    )

    if aoi_rows is None:
        logger.error("API Repo: Database query error while fetching AOI list")
        return None

    for row in aoi_rows:
        lower = row.get("lower_bound")
        upper = row.get("upper_bound")
        if not (validate_nullable_float(lower, "lower_bound") and validate_nullable_float(upper, "upper_bound")):
            return None
        response["aois"].append({
            "lower_bound": float(lower) if lower is not None else None,
            "upper_bound": float(upper) if upper is not None else None,
        })

    return response
