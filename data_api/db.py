"""Database connection helpers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2 import OperationalError
from psycopg2.extensions import connection as PGConnection

from .config import get_database_config
from .logging_config import get_logger

log = get_logger(__name__)


@contextmanager
def get_connection() -> Iterator[PGConnection]:
    """Yield a PostgreSQL connection and ensure it is closed afterwards."""

    config = get_database_config()
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=config.dbname,
            user=config.user,
            password=config.password,
            host=config.host,
            port=config.port,
            options=config.options,
        )
        yield conn
    except OperationalError:
        log.exception("Failed to establish database connection")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive close
                log.exception("Failed to close database connection cleanly")
