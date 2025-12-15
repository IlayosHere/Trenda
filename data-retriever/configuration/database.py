import os

POSTGRES_DB = {
    "dbname": os.getenv("DB_NAME", "trenda"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "options": os.getenv("DB_OPTIONS", "-c search_path=trenda"),
}
