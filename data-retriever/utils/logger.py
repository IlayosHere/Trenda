"""
Centralized Logging Module for Trenda Data Retriever.

Provides a configurable, production-grade logging system built on Python's
standard logging library. Supports multiple log levels, console output,
and optional file output.

Configuration via environment variables:
    LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
    LOG_FILE: Path to log file (default: None, console only)

Usage:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Message here")
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

# Configuration from environment
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", None)

# Log format: timestamp [LEVEL] module: message
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Maximum log file size (10 MB) and backup count
MAX_LOG_SIZE = 10 * 1024 * 1024
BACKUP_COUNT = 3

# Cache for loggers to avoid duplicate handlers
_loggers: dict[str, logging.Logger] = {}
_initialized = False


def _get_log_level() -> int:
    """Convert LOG_LEVEL string to logging constant."""
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(LOG_LEVEL, logging.INFO)


def _create_console_handler() -> logging.StreamHandler:
    """Create and configure a console (stdout) handler with UTF-8 support."""
    # On Windows, reconfigure stdout to handle Unicode properly
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            # Python < 3.7 fallback - wrap stdout
            pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(_get_log_level())
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    # Set encoding error handling to replace unsupported characters
    if hasattr(handler.stream, "reconfigure"):
        try:
            handler.stream.reconfigure(errors="replace")
        except (AttributeError, TypeError):
            pass

    return handler


def _create_file_handler(filepath: str) -> Optional[RotatingFileHandler]:
    """Create and configure a rotating file handler."""
    try:
        # Ensure directory exists
        log_dir = os.path.dirname(filepath)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        handler = RotatingFileHandler(
            filepath,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setLevel(_get_log_level())
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        return handler
    except (OSError, IOError) as exc:
        # Fall back to console-only if file creation fails
        sys.stderr.write(f"Warning: Could not create log file '{filepath}': {exc}\n")
        return None


def _initialize_root_logger() -> None:
    """Initialize the root logger with handlers."""
    global _initialized
    if _initialized:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(_get_log_level())

    # Clear any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Always add console handler
    root_logger.addHandler(_create_console_handler())

    # Optionally add file handler
    if LOG_FILE:
        file_handler = _create_file_handler(LOG_FILE)
        if file_handler:
            root_logger.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger for the given module name.

    Args:
        name: Module name (typically __name__ from the calling module)

    Returns:
        A configured logging.Logger instance

    Example:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Processing started")
        logger.error("Something went wrong")
    """
    if name in _loggers:
        return _loggers[name]

    # Ensure root logger is initialized
    _initialize_root_logger()

    # Create and cache the logger
    logger = logging.getLogger(name)
    _loggers[name] = logger

    return logger


def set_log_level(level: str) -> None:
    """
    Dynamically change the log level at runtime.

    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL
    """
    global LOG_LEVEL
    LOG_LEVEL = level.upper()
    numeric_level = _get_log_level()

    # Update root logger and all handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    for handler in root_logger.handlers:
        handler.setLevel(numeric_level)

    # Update all cached loggers
    for logger in _loggers.values():
        logger.setLevel(numeric_level)
