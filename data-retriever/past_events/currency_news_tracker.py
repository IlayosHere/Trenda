"""
Daily Currency News Tracking Table Generator

This module creates and populates a PostgreSQL table that tracks the proximity
of high-impact economic news events for each currency on a daily basis.

Value logic for each currency column:
    0  → News exists on this exact date
    1  → News exists 1 day after this date
    2  → News exists 2 days after this date
   -1  → News exists 1 day before this date
   -2  → News exists 2 days before this date
   NULL → No news within ±2 days range
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Database configuration - reads from environment variables
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "trenda"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "options": os.getenv("DB_OPTIONS", "-c search_path=trenda"),
}

# Currencies to track
TRACKED_CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD', 'AUD', 'NZD']

# SQL for creating the table
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_currency_news_tracking (
    -- Primary key: the date being tracked
    trade_date DATE NOT NULL PRIMARY KEY,
    
    -- Currency columns: relative day offset to nearest news event
    -- Using SMALLINT for compact storage (2 bytes per column)
    usd SMALLINT NULL,
    eur SMALLINT NULL,
    gbp SMALLINT NULL,
    jpy SMALLINT NULL,
    chf SMALLINT NULL,
    cad SMALLINT NULL,
    aud SMALLINT NULL,
    nzd SMALLINT NULL,
    
    -- CHECK constraints to enforce valid values: -2, -1, 0, 1, 2, or NULL
    CONSTRAINT chk_usd_range CHECK (usd IS NULL OR usd IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_eur_range CHECK (eur IS NULL OR eur IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_gbp_range CHECK (gbp IS NULL OR gbp IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_jpy_range CHECK (jpy IS NULL OR jpy IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_chf_range CHECK (chf IS NULL OR chf IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_cad_range CHECK (cad IS NULL OR cad IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_aud_range CHECK (aud IS NULL OR aud IN (-2, -1, 0, 1, 2)),
    CONSTRAINT chk_nzd_range CHECK (nzd IS NULL OR nzd IN (-2, -1, 0, 1, 2))
);
"""

# SQL for creating index
CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_daily_currency_news_date 
ON daily_currency_news_tracking(trade_date);
"""

# SQL for adding comments
ADD_COMMENTS_SQL = """
COMMENT ON TABLE daily_currency_news_tracking IS 
    'Daily tracking of currency news events proximity. Each column indicates the relative day offset to the nearest high-impact news event for that currency.';
"""

# SQL for inserting/updating data
UPSERT_SQL = """
INSERT INTO daily_currency_news_tracking 
    (trade_date, usd, eur, gbp, jpy, chf, cad, aud, nzd)
VALUES 
    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (trade_date) 
DO UPDATE SET 
    usd = EXCLUDED.usd,
    eur = EXCLUDED.eur,
    gbp = EXCLUDED.gbp,
    jpy = EXCLUDED.jpy,
    chf = EXCLUDED.chf,
    cad = EXCLUDED.cad,
    aud = EXCLUDED.aud,
    nzd = EXCLUDED.nzd;
"""


def get_db_connection():
    """Create and return a database connection."""
    return psycopg2.connect(**DB_CONFIG)


def load_forex_events_data() -> pd.DataFrame:
    """
    Load the forex past events CSV file.
    
    Returns:
        DataFrame with parsed event data
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "forex_past_events.csv")
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Economic calendar CSV not found at: {file_path}")
    
    # The CSV has no header: DateTime, Currency, Event, Description
    column_names = ['DateTime', 'Currency', 'Event', 'Description']
    df = pd.read_csv(file_path, names=column_names, on_bad_lines='skip')
    
    # Extract just the YYYY-MM-DD part and parse it as a date
    df['Date'] = pd.to_datetime(df['DateTime'].str[:10]).dt.date
    
    logger.info(f"Loaded {len(df)} events from forex_past_events.csv")
    return df


def build_currency_event_dates(df: pd.DataFrame) -> Dict[str, Set]:
    """
    Build a dictionary mapping each currency to a set of dates with events.
    
    Args:
        df: DataFrame with event data
        
    Returns:
        Dict mapping currency code to set of dates
    """
    currency_dates = {currency: set() for currency in TRACKED_CURRENCIES}
    
    for _, row in df.iterrows():
        currency = row['Currency']
        if currency == 'All':
            # "All" currency means the event applies to all tracked currencies
            for curr in TRACKED_CURRENCIES:
                currency_dates[curr].add(row['Date'])
        elif currency in TRACKED_CURRENCIES:
            currency_dates[currency].add(row['Date'])
    
    for currency, dates in currency_dates.items():
        logger.info(f"{currency}: {len(dates)} unique event dates")
    
    return currency_dates


def calculate_news_offset(target_date, currency_event_dates: Set) -> Optional[int]:
    """
    Calculate the relative offset to the nearest news event for a given date.
    
    Priority order (as specified):
        0  → News exists on this exact date
        1  → News exists 1 day after
        2  → News exists 2 days after
       -1  → News exists 1 day before
       -2  → News exists 2 days before
       None → No news within ±2 days
    
    Args:
        target_date: The date to check
        currency_event_dates: Set of dates with events for the currency
        
    Returns:
        Offset value or None if no events within range
    """
    # Priority order: 0, 1, 2, -1, -2
    offsets_priority = [0, 1, 2, -1, -2]
    
    for offset in offsets_priority:
        check_date = target_date + timedelta(days=offset)
        if check_date in currency_event_dates:
            return offset
    
    return None


def generate_daily_tracking_data(
    currency_dates: Dict[str, Set],
    start_date,
    end_date
) -> list:
    """
    Generate daily tracking data for all dates in the range.
    
    Args:
        currency_dates: Dict mapping currency to set of event dates
        start_date: Start of date range
        end_date: End of date range
        
    Returns:
        List of tuples ready for database insertion
    """
    rows = []
    current_date = start_date
    total_days = (end_date - start_date).days + 1
    
    logger.info(f"Generating data for {total_days} days from {start_date} to {end_date}")
    
    while current_date <= end_date:
        row_data = [current_date]
        
        # Calculate offset for each currency in order
        for currency in TRACKED_CURRENCIES:
            offset = calculate_news_offset(current_date, currency_dates[currency])
            row_data.append(offset)
        
        rows.append(tuple(row_data))
        current_date += timedelta(days=1)
    
    logger.info(f"Generated {len(rows)} daily tracking rows")
    return rows


def create_table(conn):
    """Create the daily_currency_news_tracking table if it doesn't exist."""
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            logger.info("Table 'daily_currency_news_tracking' created or already exists")
            
            cur.execute(CREATE_INDEX_SQL)
            logger.info("Index created or already exists")
            
            cur.execute(ADD_COMMENTS_SQL)
            logger.info("Table comments added")
            
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create table: {e}")
        raise


def insert_tracking_data(conn, rows: list, batch_size: int = 1000):
    """
    Insert tracking data into the database in batches.
    
    Args:
        conn: Database connection
        rows: List of row tuples to insert
        batch_size: Number of rows to insert per batch
    """
    total_rows = len(rows)
    inserted = 0
    
    try:
        with conn.cursor() as cur:
            # Use execute_batch for efficient bulk insertion
            execute_batch(cur, UPSERT_SQL, rows, page_size=batch_size)
            inserted = total_rows
        
        conn.commit()
        logger.info(f"Successfully inserted {inserted} rows into daily_currency_news_tracking")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to insert data: {e}")
        raise


def populate_currency_news_tracking():
    """
    Main function to populate the daily currency news tracking table.
    
    This function:
    1. Loads forex events data from CSV
    2. Builds a lookup of event dates per currency
    3. Creates the database table
    4. Generates and inserts daily tracking data
    """
    conn = None
    try:
        logger.info("=" * 60)
        logger.info("Starting Daily Currency News Tracking Table Population")
        logger.info("=" * 60)
        
        # Step 1: Load event data
        df = load_forex_events_data()
        
        # Step 2: Build currency event dates lookup
        currency_dates = build_currency_event_dates(df)
        
        # Step 3: Determine date range from the data
        all_dates = df['Date'].dropna()
        start_date = all_dates.min()
        end_date = all_dates.max()
        
        logger.info(f"Date range: {start_date} to {end_date}")
        
        # Step 4: Connect to database and create the table
        conn = get_db_connection()
        logger.info("Connected to database")
        
        create_table(conn)
        
        # Step 5: Generate daily tracking data
        rows = generate_daily_tracking_data(currency_dates, start_date, end_date)
        
        # Step 6: Insert data into database
        insert_tracking_data(conn, rows)
        
        logger.info("=" * 60)
        logger.info("Daily Currency News Tracking Table Population Complete!")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to populate currency news tracking: {e}")
        raise
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed")


def verify_table_data():
    """Verify the table was created and populated correctly."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Check total rows
            cur.execute("SELECT COUNT(*) FROM daily_currency_news_tracking")
            result = cur.fetchone()
            total_rows = result[0] if result else 0
            logger.info(f"Total rows in table: {total_rows}")
            
            # Sample some data
            cur.execute("""
                SELECT trade_date, usd, eur, gbp, jpy, chf, cad, aud, nzd 
                FROM daily_currency_news_tracking 
                ORDER BY trade_date DESC 
                LIMIT 10
            """)
            sample = cur.fetchall()
            
            logger.info("Sample of recent data:")
            for row in sample:
                logger.info(f"  {row}")
            
            # Check distribution of values for USD
            cur.execute("""
                SELECT usd, COUNT(*) as cnt 
                FROM daily_currency_news_tracking 
                GROUP BY usd 
                ORDER BY usd
            """)
            dist = cur.fetchall()
            logger.info(f"USD value distribution: {dict(dist)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return False
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Run the population script
    populate_currency_news_tracking()
    
    # Verify the results
    verify_table_data()
