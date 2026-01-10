import logging
import os
import threading
from contextlib import contextmanager
from typing import Optional

from psycopg2 import InterfaceError, OperationalError
from psycopg2.extensions import connection as PgConnection
from psycopg2.pool import SimpleConnectionPool

from configuration import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] DB: %(message)s",
    )

CONNECTION_TIMEOUT = int(os.getenv("DB_CONNECTION_TIMEOUT", "30"))


class DBConnectionError(Exception):
    """Raised when the database connection cannot be acquired."""


class DBConnectionManager:
    _pool: Optional[SimpleConnectionPool] = None
    _pool_details_logged = False
    _pool_lock = threading.Lock()

    @classmethod
    def init_pool(cls, minconn: Optional[int] = None, maxconn: Optional[int] = None) -> SimpleConnectionPool:
        if cls._pool:
            return cls._pool

        with cls._pool_lock:
            if cls._pool:
                return cls._pool

            # Deferred import to avoid circular import
            from configuration.db_config import POSTGRES_DB

            min_conn = int(os.getenv("DB_POOL_MIN_CONN", minconn or 1))
            max_conn = int(os.getenv("DB_POOL_MAX_CONN", maxconn or 10))

            try:
                db_config = POSTGRES_DB.copy()
                if "connect_timeout" not in db_config:
                    db_config["connect_timeout"] = CONNECTION_TIMEOUT

                cls._pool = SimpleConnectionPool(min_conn, max_conn, **db_config)
            except Exception as exc:
                cls._pool = None
                logger.error(f"DB_POOL_INIT_FAILED: {exc}")
                log.error("DB_POOL_INIT_FAILED|error=%s", exc, exc_info=True)
                raise

        cls._log_pool_details()
        log.info("DB_POOL_INITIALIZED|min=%d|max=%d", min_conn, max_conn)
        return cls._pool

    @classmethod
    def _log_pool_details(cls) -> None:
        if cls._pool_details_logged or not cls._pool:
            return

        conn = None
        close_conn = False
        try:
            with cls._pool_lock:
                conn = cls._pool.getconn()

            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_schema();")
                db_name, schema = cur.fetchone()
                log.info("DB_POOL_READY|database=%s|schema=%s", db_name, schema)
                cls._pool_details_logged = True
        except (OperationalError, InterfaceError) as exc:
            close_conn = True
            logger.error(f"DB_METADATA_QUERY_FAILED: {exc}")
            log.error("DB_METADATA_QUERY_FAILED|error=%s", exc, exc_info=True)
        except Exception as exc:
            logger.error(f"DB_METADATA_QUERY_FAILED: {exc}")
            log.error("DB_METADATA_QUERY_FAILED|error=%s", exc, exc_info=True)
        finally:
            if conn and cls._pool:
                with cls._pool_lock:
                    cls._pool.putconn(conn, close=close_conn)

    @classmethod
    def _require_pool(cls) -> SimpleConnectionPool:
        return cls.init_pool()

    @classmethod
    def get_connection(cls) -> PgConnection:
        try:
            return cls._require_pool().getconn()
        except Exception as exc:
            logger.error(f"DB_CONNECTION_RETRIEVE_FAILED: {exc}")
            log.error("DB_CONNECTION_RETRIEVE_FAILED|error=%s", exc, exc_info=True)
            raise DBConnectionError("Failed to acquire database connection") from exc

    @classmethod
    def _release_connection_safely(
        cls, conn: Optional[PgConnection], error: Optional[Exception] = None
    ) -> None:
        if not conn or not cls._pool:
            return

        close_conn = False

        if error and isinstance(error, (OperationalError, InterfaceError)):
            close_conn = True
            log.warning("DB_CLOSING_BAD_CONNECTION|error_type=%s", type(error).__name__)

        try:
            cls._pool.putconn(conn, close=close_conn)
        except Exception as exc:
            logger.error(f"DB_CONNECTION_RELEASE_FAILED: {exc}")
            log.error("DB_CONNECTION_RELEASE_FAILED|error=%s", exc, exc_info=True)

    @classmethod
    @contextmanager
    def get_connection_context(cls):
        conn = None
        error = None
        try:
            conn = cls.get_connection()
            yield conn
        except Exception as exc:
            error = exc
            raise
        finally:
            if conn is not None:
                cls._release_connection_safely(conn, error)

    @classmethod
    def close_pool(cls) -> None:
        with cls._pool_lock:
            if cls._pool:
                try:
                    cls._pool.closeall()
                    log.info("DB_POOL_CLOSED")
                except Exception as exc:
                    logger.error(f"DB_POOL_CLOSE_FAILED: {exc}")
                    log.error("DB_POOL_CLOSE_FAILED|error=%s", exc, exc_info=True)
                finally:
                    cls._pool = None
                    cls._pool_details_logged = False

    @classmethod
    def get_pool_stats(cls) -> dict:
        if not cls._pool:
            return {"status": "not_initialized"}

        try:
            return {
                "status": "active",
                "minconn": cls._pool.minconn,
                "maxconn": cls._pool.maxconn,
            }
        except Exception as exc:
            log.error("DB_POOL_STATS_ERROR|error=%s", exc)
            return {"status": "error", "error": str(exc)}
