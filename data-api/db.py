import logging
import os
from typing import Any, Callable, Optional, Sequence, TypeVar

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extensions import connection as PgConnection, cursor as PgCursor
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] API_DB: %(message)s",
    )

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "trenda"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "options": os.getenv("DB_OPTIONS", "-c search_path=trenda"),
}

_pool: Optional[SimpleConnectionPool] = None
_pool_details_logged = False
_T = TypeVar("_T")

if not DB_CONFIG["password"]:
    log.warning("DB_PASSWORD environment variable not set. Database connection will likely fail.")


def init_pool(minconn: Optional[int] = None, maxconn: Optional[int] = None) -> SimpleConnectionPool:
    global _pool
    if _pool:
        return _pool

    min_conn = int(os.getenv("DB_POOL_MIN_CONN", minconn or 1))
    max_conn = int(os.getenv("DB_POOL_MAX_CONN", maxconn or 5))

    try:
        _pool = SimpleConnectionPool(min_conn, max_conn, **DB_CONFIG)
        _log_pool_details()
        return _pool
    except Exception as exc:
        _pool = None
        log.error("DB_POOL_INIT_FAILED|error=%s", exc, exc_info=True)
        raise


def _log_pool_details() -> None:
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
    try:
        return _require_pool().getconn()
    except Exception as exc:
        log.error("DB_CONNECTION_RETRIEVE_FAILED|error=%s", exc, exc_info=True)
        return None


def release_connection(conn: Optional[PgConnection]) -> None:
    if conn and _pool:
        try:
            _pool.putconn(conn)
        except Exception as exc:
            log.error("DB_CONNECTION_RELEASE_FAILED|error=%s", exc, exc_info=True)


def close_pool() -> None:
    global _pool
    if _pool:
        try:
            _pool.closeall()
        except Exception as exc:
            log.error("DB_POOL_CLOSE_FAILED|error=%s", exc, exc_info=True)
        finally:
            _pool = None


def _handle_error(context: str, exc: Exception, conn: PgConnection) -> None:
    log.error("DB_ERROR|context=%s|error=%s", context, exc, exc_info=True)
    try:
        conn.rollback()
    except Exception as rollback_exc:
        log.error("DB_ROLLBACK_FAILED|context=%s|error=%s", context, rollback_exc, exc_info=True)


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
    sql: str, param_sets: Sequence[Sequence[Any]], context: str = "batch"
) -> bool:
    return bool(_execute(sql, params=list(param_sets), many=True, context=context))


def fetch_one(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "fetch_one",
):
    return _execute(sql, params=params, fetch="one", cursor_factory=cursor_factory, context=context)


def fetch_all(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "fetch_all",
):
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
        log.error("DB_VALIDATION|context=symbol|error=invalid or empty")
        return False
    return True


def validate_timeframe(timeframe: str) -> bool:
    if not isinstance(timeframe, str) or not timeframe.strip():
        log.error("DB_VALIDATION|context=timeframe|error=invalid or empty")
        return False
    return True


def validate_nullable_float(value: Optional[float], field: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, (int, float)):
        log.error("DB_VALIDATION|context=%s|error=expected number or None", field)
        return False
    return True
