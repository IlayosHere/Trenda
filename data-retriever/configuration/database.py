<<<<<<< HEAD
import os

POSTGRES_DB = {
    "dbname": os.getenv("DB_NAME", "trenda"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"), # No default for password!
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "options": os.getenv("DB_OPTIONS", "-c search_path=trenda")
}

# Add a check for the essential password
if POSTGRES_DB["password"] is None:
    print("⚠️ WARNING: DB_PASSWORD environment variable not set.")
    # Consider raising an error or exiting if the password is required to run
    # raise ValueError("DB_PASSWORD must be set in the environment or .env file")
=======
POSTGRES_DB = {
    "dbname": "trenda",
    "user": "postgres",
    "password": "heblish123",
    "host": "localhost",
    "port": "5432",
    "options": "-c search_path=trenda"
}
>>>>>>> 410b244b1629f2d0ab46bb027e831b4a1ce12b6e
