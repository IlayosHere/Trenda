import logging
import sys
import os
import threading
# from logging.handlers import RotatingFileHandler

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-initialize formatters for each level to optimize performance
        self._formatters = {
            level: logging.Formatter(
                f"{color}{self.BASE_FORMAT}{self.RESET}", 
                datefmt=self.DATE_FORMAT
            )
            for level, color in {
                logging.DEBUG: self.CYAN,
                logging.INFO: self.GREEN,
                logging.WARNING: self.YELLOW,
                logging.ERROR: self.RED,
                logging.CRITICAL: self.BOLD_RED,
            }.items()
        }
        self._default_formatter = logging.Formatter(
            f"{self.RESET}{self.BASE_FORMAT}{self.RESET}", 
            datefmt=self.DATE_FORMAT
        )

    def format(self, record):
        formatter = self._formatters.get(record.levelno, self._default_formatter)
        return formatter.format(record)

def setup_global_logging():
    """Configures the root logger with Console output (Colored)."""
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

        _is_configured = True

def get_logger(name: str) -> logging.Logger:
    """
    The main entry point: Returns a logger instance for a given name.
    Ensures global logging is configured exactly once.
    """
    if not _is_configured:
        setup_global_logging()
    return logging.getLogger(name)
