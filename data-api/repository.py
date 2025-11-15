import os
import psycopg2
from psycopg2.extras import RealDictCursor # To get results as dictionaries
from typing import Optional, List, Dict, Any
import logging
from dotenv import load_dotenv

# --- Load Environment Variables ---
# Ensure environment variables are loaded if this module is imported early
load_dotenv()

# --- Setup Logging ---
log = logging.getLogger(__name__)
# Basic config if run standalone, actual config often done in api.py
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] API_Repo: %(message)s')

# --- Database Configuration ---~~
# Read directly from environment variables (populated by .env or deployment config)
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "trenda"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"), # Should definitely be set in .env
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "options": os.getenv("DB_OPTIONS", "-c search_path=trenda")
}

if not DB_CONFIG["password"]:
    log.warning("DB_PASSWORD environment variable not set. Database connection will likely fail.")

# --- Connection Management ---

def get_db_connection() -> Optional[psycopg2.extensions.connection]:
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        log.debug("Database connection successful.")
        return conn
    except psycopg2.OperationalError as e:
        log.error(f"DATABASE CONNECTION FAILED: {e}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"Unexpected error connecting to database: {e}", exc_info=True)
        return None

def close_db_connection(conn: Optional[psycopg2.extensions.connection]) -> None:
    """ Closes the database connection if it's open. """
    if conn:
        try:
            conn.close()
            log.debug("Database connection closed.")
        except Exception as e:
            log.error(f"Error closing database connection: {e}", exc_info=True)

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
    conn = get_db_connection()
    if not conn:
        log.error("API Fetch: Database connection failed.")
        return None # Indicate connection failure

    results: List[Dict[str, Any]] = []
    try:
        # Use RealDictCursor to get rows as dictionaries directly
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql)
            results = cursor.fetchall() # fetchall returns a list of dicts
        log.info(f"API Repo: Retrieved {len(results)} records.")
        return results

    except psycopg2.Error as db_err:
        log.error(f"API Repo: Database query error: {db_err}", exc_info=True)
        return None # Indicate DB operation failure
    except Exception as e:
        log.error(f"API Repo: Unexpected error during fetch: {e}", exc_info=True)
        return None # Indicate other failure
    finally:
        close_db_connection(conn)


def fetch_aoi_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch AOI data along with trend levels for a specific symbol/timeframe."""

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

    conn = get_db_connection()
    if not conn:
        log.error("API Fetch AOI: Database connection failed.")
        return None

    response: Dict[str, Any] = {
        "symbol": symbol,
        "low": None,
        "high": None,
        "aois": [],
    }

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(trend_sql, (symbol, "4H"))
            trend_row = cursor.fetchone()

            if trend_row:
                high = trend_row.get("high")
                low = trend_row.get("low")
                response["high"] = float(high) if high is not None else None
                response["low"] = float(low) if low is not None else None

            cursor.execute(aoi_sql, (symbol))
            print(cursor.query.decode("utf-8"))
            aoi_rows = cursor.fetchall()
            response["aois"] = []
            for row in aoi_rows:
               response["aois"].append({
                    "lower_bound": float(row["lower_bound"]) if row["lower_bound"] is not None else None,
                    "upper_bound": float(row["upper_bound"]) if row["upper_bound"] is not None else None,
                })

        return response

    except psycopg2.Error as db_err:
        log.error(f"API Repo: Database query error while fetching AOI: {db_err}", exc_info=True)
        return None
    except Exception as e:
        log.error(f"API Repo: Unexpected error during AOI fetch: {e}", exc_info=True)
        return None
    finally:
        close_db_connection(conn)
