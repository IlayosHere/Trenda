"""Centralised logging configuration utilities."""
from __future__ import annotations

import logging
from typing import Optional


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_LEVEL = logging.INFO


def configure_logging(level: int = DEFAULT_LEVEL) -> None:
    """Configure root logging if it has not been configured yet."""

    if logging.getLogger().handlers:
        return

    logging.basicConfig(level=level, format=LOG_FORMAT)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a module specific logger with shared configuration."""

    configure_logging()
    return logging.getLogger(name)
