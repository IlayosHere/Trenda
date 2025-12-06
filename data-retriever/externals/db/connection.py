import psycopg2

from configuration import POSTGRES_DB
import utils.display as display


def get_db_connection():
    """Establish a Postgres connection using configured credentials."""
    try:
        conn = psycopg2.connect(**POSTGRES_DB)
        cur = conn.cursor()
        cur.execute("SELECT current_database(), current_schema();")
        print("Connected to DB and schema:", cur.fetchone())
        return conn
    except psycopg2.OperationalError as e:
        display.print_error(f"DATABASE CONNECTION FAILED: {e}")
        return None
