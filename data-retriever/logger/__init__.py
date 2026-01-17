import logging
import sys
import os
import threading
from logging.handlers import RotatingFileHandler

# Thread-safe initialization flag
_lock = threading.Lock()
_is_configured = False

class BestPracticeColorFormatter(logging.Formatter):
    """A clean, colored formatter for terminal output."""
    
    # ANSI Color Codes
    BLUE = "\x1b[34;1m"
    CYAN = "\x1b[36m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    # Minimalist and professional format
    BASE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    DATE_FORMAT = "%H:%M:%S"

    COLORS = {
        logging.DEBUG: CYAN,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        log_fmt = f"{color}{self.BASE_FORMAT}{self.RESET}"
        formatter = logging.Formatter(log_fmt, datefmt=self.DATE_FORMAT)
        return formatter.format(record)

def setup_global_logging():
    """Configures the root logger with dual outputs: Console (Colored) and File (Plain)."""
    global _is_configured
    
    with _lock:
        if _is_configured:
            return
            
        # 1. Configure levels (from environment or default to INFO)
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        
        root = logging.getLogger()
        root.setLevel(log_level)
        
        # Remove any existing handlers to ensure we don't double-log
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        # 2. Console Handler (Standard Output with Colors)
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(BestPracticeColorFormatter())
        root.addHandler(console)

        # 3. File Handler (Persistent logs with Rotation)
        try:
            # Create a 'logs' directory if it doesn't exist
            log_dir = "logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
                
            file_handler = RotatingFileHandler(
                filename=os.path.join(log_dir, "trenda.log"),
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding='utf-8'
            )
            # Use a plain, more detailed format for the file logs (no ANSI codes)
            file_formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_formatter)
            root.addHandler(file_handler)
        except Exception:
            # If we can't write to disk (e.g. permission issues), we just stick to console
            pass

        _is_configured = True

def get_logger(name: str) -> logging.Logger:
    """
    The main entry point: Returns a logger instance for a given name.
    Ensures global logging is configured exactly once.
    """
    if not _is_configured:
        setup_global_logging()
    return logging.getLogger(name)
