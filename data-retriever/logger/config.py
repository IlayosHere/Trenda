import os

# Configuration from environment
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", None)

# Log format: timestamp [LEVEL] module: message
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Maximum log file size (10 MB) and backup count
MAX_LOG_SIZE = 10 * 1024 * 1024
BACKUP_COUNT = 3

# Separator for logging
SEPARATOR = "-" * 50
