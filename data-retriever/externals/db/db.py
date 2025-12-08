import logging
import os
from typing import Any, Callable, Iterable, Optional, Sequence, TypeVar

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extensions import connection as PgConnection, cursor as PgCursor

from configuration import POSTGRES_DB
import utils.display as display


log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] DB: %(message)s",
    )

_pool: Optional[SimpleConnectionPool] = None
_pool_details_logged = False
_T = TypeVar("_T")


def init_pool(minconn: Optional[int] = None, maxconn: Optional[int] = None) -> SimpleConnectionPool:
    """Initialize and return the global connection pool."""
    global _pool
    if _pool:
        return _pool

    min_conn = int(os.getenv("DB_POOL_MIN_CONN", minconn or 1))
    max_conn = int(os.getenv("DB_POOL_MAX_CONN", maxconn or 5))

    try:
        _pool = SimpleConnectionPool(min_conn, max_conn, **POSTGRES_DB)
        _log_pool_details()
        return _pool
    except Exception as exc:
        _pool = None
        display.print_error(f"DB_POOL_INIT_FAILED: {exc}")
        log.error("DB_POOL_INIT_FAILED|error=%s", exc, exc_info=True)
        raise


def _log_pool_details() -> None:
    """Log the database and schema once when the pool is created."""
    global _pool_details_logged
    if _pool_details_logged or not _pool:
        return

    conn = None
    try:
        conn = _pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_schema();")
            db_name, schema = cur.fetchone()
            log.info("DB_POOL_READY|database=%s|schema=%s", db_name, schema)
            _pool_details_logged = True
    except Exception as exc:
        display.print_error(f"DB_METADATA_QUERY_FAILED: {exc}")
        log.error("DB_METADATA_QUERY_FAILED|error=%s", exc, exc_info=True)
    finally:
        if conn:
            _pool.putconn(conn)


def _require_pool() -> SimpleConnectionPool:
    pool = init_pool()
    if not pool:
        raise psycopg2.OperationalError("Database connection pool is not available")
    return pool


def get_connection() -> Optional[PgConnection]:
    """Retrieve a connection from the global pool."""
    try:
        return _require_pool().getconn()
    except Exception as exc:
        display.print_error(f"DB_CONNECTION_RETRIEVE_FAILED: {exc}")
        log.error("DB_CONNECTION_RETRIEVE_FAILED|error=%s", exc, exc_info=True)
        return None


def release_connection(conn: Optional[PgConnection]) -> None:
    """Return a connection to the pool if possible."""
    if conn and _pool:
        try:
            _pool.putconn(conn)
        except Exception as exc:
            display.print_error(f"DB_CONNECTION_RELEASE_FAILED: {exc}")
            log.error("DB_CONNECTION_RELEASE_FAILED|error=%s", exc, exc_info=True)


def close_pool() -> None:
    """Close all idle connections in the pool."""
    global _pool
    if _pool:
        try:
            _pool.closeall()
        except Exception as exc:
            display.print_error(f"DB_POOL_CLOSE_FAILED: {exc}")
            log.error("DB_POOL_CLOSE_FAILED|error=%s", exc, exc_info=True)
        finally:
            _pool = None


def _handle_error(context: str, exc: Exception, conn: PgConnection) -> None:
    display.print_error(f"DB_ERROR[{context}]: {exc}")
    log.error("DB_ERROR|context=%s|error=%s", context, exc, exc_info=True)
    try:
        conn.rollback()
    except Exception as rollback_exc:
        display.print_error(f"DB_ROLLBACK_FAILED[{context}]: {rollback_exc}")
        log.error(
            "DB_ROLLBACK_FAILED|context=%s|error=%s", context, rollback_exc, exc_info=True
        )


def _execute(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    fetch: Optional[str] = None,
    many: bool = False,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "",
) -> Any:
    conn = get_connection()
    if not conn:
        return None

    result: Any = True if fetch is None else None
    try:
        with conn:
            with conn.cursor(cursor_factory=cursor_factory) as cursor:
                if many:
                    cursor.executemany(sql, params or [])
                else:
                    cursor.execute(sql, params)

                if fetch == "one":
                    result = cursor.fetchone()
                elif fetch == "all":
                    result = cursor.fetchall()
            conn.commit()
    except Exception as exc:
        result = None
        _handle_error(context or sql, exc, conn)
    finally:
        release_connection(conn)
    return result


def execute_non_query(
    sql: str, params: Optional[Sequence[Any]] = None, context: str = "non_query"
) -> bool:
    return bool(_execute(sql, params=params, fetch=None, context=context))


def execute_many(
    sql: str, param_sets: Iterable[Sequence[Any]], context: str = "batch"
) -> bool:
    return bool(_execute(sql, params=list(param_sets), many=True, context=context))


def fetch_one(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "fetch_one",
) -> Optional[Any]:
    return _execute(sql, params=params, fetch="one", cursor_factory=cursor_factory, context=context)


def fetch_all(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "fetch_all",
) -> Optional[Any]:
    return _execute(sql, params=params, fetch="all", cursor_factory=cursor_factory, context=context)


def execute_transaction(
    work: Callable[[PgCursor], _T],
    context: str = "transaction",
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
) -> Optional[_T]:
    conn = get_connection()
    if not conn:
        return None

    try:
        with conn:
            with conn.cursor(cursor_factory=cursor_factory) as cursor:
                result = work(cursor)
            conn.commit()
            return result
    except Exception as exc:
        _handle_error(context, exc, conn)
        return None
    finally:
        release_connection(conn)


def validate_symbol(symbol: str) -> bool:
    if not isinstance(symbol, str) or not symbol.strip():
        display.print_error("DB_VALIDATION: symbol must be a non-empty string")
        return False
    return True


def validate_timeframe(timeframe: str) -> bool:
    if not isinstance(timeframe, str) or not timeframe.strip():
        display.print_error("DB_VALIDATION: timeframe must be a non-empty string")
        return False
    return True


def validate_nullable_float(value: Optional[float], field: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, (int, float)):
        display.print_error(f"DB_VALIDATION: {field} must be a number or None")
        return False
    return True


def validate_aoi(aoi: dict) -> bool:
    lower = aoi.get("lower_bound")
    upper = aoi.get("upper_bound")
    if not validate_nullable_float(lower, "lower_bound"):
        return False
    if not validate_nullable_float(upper, "upper_bound"):
        return False
    return True
