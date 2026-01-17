import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict
from .config import LOG_LEVEL, LOG_FILE, LOG_FORMAT, DATE_FORMAT, MAX_LOG_SIZE, BACKUP_COUNT, SEPARATOR

class TrendaLogger:
    _instance: Optional['TrendaLogger'] = None
    _loggers: Dict[str, logging.Logger] = {}
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TrendaLogger, cls).__new__(cls)
        return cls._instance

    def _get_numeric_level(self, level_str: str) -> int:
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return level_map.get(level_str.upper(), logging.INFO)

    def _initialize_root_logger(self):
        if self._initialized:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(self._get_numeric_level(LOG_LEVEL))
        root_logger.handlers.clear()

        # Console handler
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except AttributeError:
                pass
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root_logger.addHandler(console_handler)

        # File handler
        if LOG_FILE:
            try:
                log_dir = os.path.dirname(LOG_FILE)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)

                file_handler = RotatingFileHandler(
                    LOG_FILE,
                    maxBytes=MAX_LOG_SIZE,
                    backupCount=BACKUP_COUNT,
                    encoding="utf-8",
                )
                file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
                root_logger.addHandler(file_handler)
            except Exception as e:
                sys.stderr.write(f"Warning: Could not create log file '{LOG_FILE}': {e}\n")

        self._initialized = True
        
        # Reduce APScheduler verbosity (hide "Added job" messages)
        logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
        logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

    def get_logger(self, name: str) -> logging.Logger:
        if not self._initialized:
            self._initialize_root_logger()
        
        if name not in self._loggers:
            # We add a wrapper to the logger to include our extra methods if needed
            # or just return a standard logger that we've configured.
            # To support separation() and clean(), we should probably wrap or extend.
            logger = logging.getLogger(name)
            self._loggers[name] = logger
        
        return self._loggers[name]

    def separation(self, logger_name: Optional[str] = None):
        """Logs a separation line."""
        target = logging.getLogger(logger_name) if logger_name else logging.getLogger()
        target.info(SEPARATOR)

    def clean(self):
        """Clears the current log file if it exists."""
        if LOG_FILE and os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'w') as f:
                    f.truncate(0)
                logging.info(f"Log file {LOG_FILE} cleaned.")
            except Exception as e:
                logging.error(f"Failed to clean log file: {e}")

# Helper functions for easy access
_registry = TrendaLogger()

def get_logger(name: str) -> logging.Logger:
    return _registry.get_logger(name)

def separation(logger_name: Optional[str] = None):
    _registry.separation(logger_name)

def clean():
    _registry.clean()
