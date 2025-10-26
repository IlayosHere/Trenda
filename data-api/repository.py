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