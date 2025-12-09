import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Optional, Sequence, TypeVar, Union

from psycopg2 import OperationalError, InterfaceError
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
_pool_lock = threading.Lock()
_T = TypeVar("_T")

# Configuration constants
MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("DB_RETRY_DELAY", "0.5"))
CONNECTION_TIMEOUT = int(os.getenv("DB_CONNECTION_TIMEOUT", "30"))


class DBConnectionError(Exception):
    """Raised when the database connection cannot be acquired."""


class DBDoNotRetryError(Exception):
    """Raised for errors that should never be retried (e.g., constraint violations)."""


def init_pool(minconn: Optional[int] = None, maxconn: Optional[int] = None) -> SimpleConnectionPool:
    global _pool
    if _pool:
        return _pool

    # First: create the pool under the lock
    with _pool_lock:
        if _pool:
            return _pool

        min_conn = int(os.getenv("DB_POOL_MIN_CONN", minconn or 1))
        max_conn = int(os.getenv("DB_POOL_MAX_CONN", maxconn or 10))

        try:
            db_config = POSTGRES_DB.copy()
            if "connect_timeout" not in db_config:
                db_config["connect_timeout"] = CONNECTION_TIMEOUT

            _pool = SimpleConnectionPool(min_conn, max_conn, **db_config)
        except Exception as exc:
            _pool = None
            display.print_error(f"DB_POOL_INIT_FAILED: {exc}")
            log.error("DB_POOL_INIT_FAILED|error=%s", exc, exc_info=True)
            raise

    # Second: use the pool *outside* the lock
    _log_pool_details()
    log.info("DB_POOL_INITIALIZED|min=%d|max=%d", min_conn, max_conn)
    return _pool



def _log_pool_details() -> None:
    """Log the database and schema once when the pool is created."""
    global _pool_details_logged
    if _pool_details_logged or not _pool:
        return

    conn = None
    close_conn = False
    try:
        with _pool_lock:
            conn = _pool.getconn()
        
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_schema();")
            db_name, schema = cur.fetchone()
            log.info("DB_POOL_READY|database=%s|schema=%s", db_name, schema)
            _pool_details_logged = True
    except (OperationalError, InterfaceError) as exc:
        close_conn = True
        display.print_error(f"DB_METADATA_QUERY_FAILED: {exc}")
        log.error("DB_METADATA_QUERY_FAILED|error=%s", exc, exc_info=True)
    except Exception as exc:
        display.print_error(f"DB_METADATA_QUERY_FAILED: {exc}")
        log.error("DB_METADATA_QUERY_FAILED|error=%s", exc, exc_info=True)
    finally:
        if conn and _pool:
            with _pool_lock:
                _pool.putconn(conn, close=close_conn)


def _require_pool() -> SimpleConnectionPool:
    return init_pool()


def get_connection() -> PgConnection:
    """Retrieve a connection from the global pool."""
    try:
        # SimpleConnectionPool is thread-safe, no lock needed here
        return _require_pool().getconn()
    except Exception as exc:
        display.print_error(f"DB_CONNECTION_RETRIEVE_FAILED: {exc}")
        log.error("DB_CONNECTION_RETRIEVE_FAILED|error=%s", exc, exc_info=True)
        raise DBConnectionError("Failed to acquire database connection") from exc


def _release_connection_safely(conn: Optional[PgConnection], error: Optional[Exception] = None) -> None:
    """
    Centralized connection cleanup logic.
    Closes the connection if it's broken, otherwise returns it to the pool.
    """
    if not conn or not _pool:
        return
    
    close_conn = False
    
    if error and isinstance(error, (OperationalError, InterfaceError)):
        close_conn = True
        log.warning("DB_CLOSING_BAD_CONNECTION|error_type=%s", type(error).__name__)
    
    try:
        _pool.putconn(conn, close=close_conn)
    except Exception as exc:
        display.print_error(f"DB_CONNECTION_RELEASE_FAILED: {exc}")
        log.error("DB_CONNECTION_RELEASE_FAILED|error=%s", exc, exc_info=True)


@contextmanager
def get_connection_context():
    """Context manager for safe connection handling."""
    conn = None
    error = None
    try:
        conn = get_connection()
        yield conn
    except Exception as exc:
        error = exc
        raise
    finally:
        if conn is not None:
            _release_connection_safely(conn, error)


def close_pool() -> None:
    """Close all idle connections in the pool."""
    global _pool, _pool_details_logged
    
    with _pool_lock:
        if _pool:
            try:
                _pool.closeall()
                log.info("DB_POOL_CLOSED")
            except Exception as exc:
                display.print_error(f"DB_POOL_CLOSE_FAILED: {exc}")
                log.error("DB_POOL_CLOSE_FAILED|error=%s", exc, exc_info=True)
            finally:
                _pool = None
                _pool_details_logged = False


def _truncate_sql(sql: str, limit: int = 150) -> str:
    """Truncate SQL string for logging."""
    return sql if len(sql) <= limit else f"{sql[:limit]}...(truncated)"


def _log_sql_error(context: str, sql: str, params: Optional[Sequence[Any]], exc: Exception) -> None:
    """Log SQL errors with proper context separation."""
    log.error(
        "DB_ERROR|context=%s|sql=%s|params=%s|error=%s",
        context,
        _truncate_sql(sql),
        params,
        exc,
        exc_info=True,
    )
    display.print_error(f"DB_ERROR[{context}]: {exc}")


def _is_retryable_error(exc: Exception) -> bool:
    """
    Determine if an error is worth retrying.
    Only retry transient connection/network errors and specific database errors.
    """
    # Connection-level errors - always retry
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    
    # Check for specific PostgreSQL error codes that are retryable
    if hasattr(exc, 'pgcode') and exc.pgcode:
        # 40P01: deadlock_detected
        # 40001: serialization_failure
        # 08000: connection_exception
        # 08003: connection_does_not_exist
        # 08006: connection_failure
        # 08001: sqlclient_unable_to_establish_sqlconnection
        # 08004: sqlserver_rejected_establishment_of_sqlconnection
        # 57P03: cannot_connect_now
        retryable_codes = ['40P01', '40001', '08000', '08001', '08003', '08004', '08006', '57P03']
        return exc.pgcode in retryable_codes
    
    return False


def _is_do_not_retry_error(exc: Exception) -> bool:
    """Check if error should never be retried."""
    if isinstance(exc, DBDoNotRetryError):
        return True
    
    # Check for constraint violations and other non-retryable errors
    if hasattr(exc, 'pgcode') and exc.pgcode:
        # 23xxx: integrity constraint violations (unique, foreign key, check, etc.)
        # 42xxx: syntax errors, undefined objects
        non_retryable_prefixes = ['23', '42']
        return any(exc.pgcode.startswith(prefix) for prefix in non_retryable_prefixes)
    
    return False


def _execute_with_retry(
    operation: Callable[[], _T],
    context: str = "",
    retry: bool = True,
    max_retries: int = MAX_RETRIES,
) -> _T:
    """Execute an operation with automatic retry on transient failures."""
    if not retry:
        return operation()
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as exc:
            last_exception = exc
            
            # Never retry certain errors
            if _is_do_not_retry_error(exc):
                raise
            
            # Don't retry if not a retryable error or if we're on the last attempt
            if not _is_retryable_error(exc) or attempt == max_retries - 1:
                raise
            
            delay = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
            log.warning(
                "DB_RETRY|context=%s|attempt=%d|max=%d|delay=%.2f|error=%s",
                context,
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            time.sleep(delay)
    
    raise last_exception


def _validate_batch_params(params: Any) -> None:
    """Validate parameters for batch execution."""
    if params is None or not isinstance(params, (list, tuple)):
        raise ValueError("Batch parameters must be a list or tuple")
    
    for idx, param_set in enumerate(params):
        if not isinstance(param_set, (list, tuple)):
            raise ValueError(
                f"Batch parameter set at index {idx} must be a list or tuple"
            )


def _execute_sql(
    cursor: PgCursor,
    sql: str,
    params: Optional[Sequence[Any]] = None,
    many: bool = False,
) -> None:
    """Execute SQL statement with appropriate method."""
    if many:
        cursor.executemany(sql, params)
    else:
        cursor.execute(sql, params)


def _fetch_results(cursor: PgCursor, fetch: Optional[str]) -> Any:
    """Fetch results based on fetch mode."""
    if fetch == "one":
        return cursor.fetchone()
    elif fetch == "all":
        rows = cursor.fetchall()
        return rows if rows is not None else []
    else:
        return True


def _execute(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    fetch: Optional[str] = None,
    many: bool = False,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "",
    retry: bool = True,
) -> Any:
    """Execute SQL with automatic connection management and retry logic."""
    
    def operation():
        conn: Optional[PgConnection] = None
        error: Optional[Exception] = None
        
        try:
            conn = get_connection()
            
            # Validate batch parameters if needed
            if many:
                _validate_batch_params(params)
            
            with conn:
                with conn.cursor(cursor_factory=cursor_factory) as cursor:
                    _execute_sql(cursor, sql, params, many)
                    result = _fetch_results(cursor, fetch)
            
            return result
            
        except Exception as exc:
            error = exc
            _log_sql_error(context, sql, params, exc)
            raise
        finally:
            if conn is not None:
                _release_connection_safely(conn, error)
    
    return _execute_with_retry(operation, context=context, retry=retry)


def execute_non_query(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    context: str = "non_query",
    retry: bool = True,
) -> bool:
    """Execute a non-query SQL statement (INSERT, UPDATE, DELETE)."""
    return bool(_execute(sql, params=params, fetch=None, context=context, retry=retry))


def execute_many(
    sql: str,
    param_sets: Iterable[Sequence[Any]],
    context: str = "batch",
    retry: bool = True,
) -> bool:
    """Execute a batch operation with multiple parameter sets."""
    params_list: Union[Iterable[Sequence[Any]], list[Sequence[Any]]]
    if isinstance(param_sets, (list, tuple)):
        params_list = param_sets
    else:
        params_list = list(param_sets)
    return bool(_execute(sql, params=params_list, many=True, context=context, retry=retry))


def fetch_one(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "fetch_one",
    retry: bool = True,
) -> Optional[Any]:
    """Fetch a single row from the database."""
    return _execute(
        sql,
        params=params,
        fetch="one",
        cursor_factory=cursor_factory,
        context=context,
        retry=retry,
    )


def fetch_all(
    sql: str,
    params: Optional[Sequence[Any]] = None,
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    context: str = "fetch_all",
    retry: bool = True,
) -> list[Any]:
    """Fetch all rows from the database."""
    return _execute(
        sql,
        params=params,
        fetch="all",
        cursor_factory=cursor_factory,
        context=context,
        retry=retry,
    )


def execute_transaction(
    work: Callable[[PgCursor], _T],
    context: str = "transaction",
    cursor_factory: Optional[Callable[..., PgCursor]] = None,
    retry: bool = True,
) -> _T:
    """Execute a function within a database transaction with retry logic."""
    
    def operation():
        conn: Optional[PgConnection] = None
        error: Optional[Exception] = None
        
        try:
            conn = get_connection()
            
            with conn:
                with conn.cursor(cursor_factory=cursor_factory) as cursor:
                    result = work(cursor)
                return result
                
        except Exception as exc:
            error = exc
            _log_sql_error(context, "<transaction>", None, exc)
            raise
        finally:
            if conn is not None:
                _release_connection_safely(conn, error)
    
    return _execute_with_retry(operation, context=context, retry=retry)


def get_pool_stats() -> dict:
    """Get current pool statistics for monitoring."""
    if not _pool:
        return {"status": "not_initialized"}
    
    try:
        return {
            "status": "active",
            "minconn": _pool.minconn,
            "maxconn": _pool.maxconn,
        }
    except Exception as exc:
        log.error("DB_POOL_STATS_ERROR|error=%s", exc)
        return {"status": "error", "error": str(exc)}


# ============================================================================
# Validation Functions
# ============================================================================

def validate_symbol(symbol: str) -> Optional[str]:
    """Validate and normalize a trading symbol."""
    if not isinstance(symbol, str) or not symbol.strip():
        display.print_error("DB_VALIDATION: symbol must be a non-empty string")
        return None

    normalized = symbol.strip().upper()

    if len(normalized) > 20:
        display.print_error("DB_VALIDATION: symbol must be 20 characters or fewer")
        return None

    if not normalized.isalnum():
        display.print_error("DB_VALIDATION: symbol must be alphanumeric")
        return None

    return normalized


def validate_timeframe(timeframe: str) -> Optional[str]:
    """Validate and normalize a timeframe string."""
    if not isinstance(timeframe, str) or not timeframe.strip():
        display.print_error("DB_VALIDATION: timeframe must be a non-empty string")
        return None

    normalized = timeframe.strip().upper()

    if len(normalized) > 20:
        display.print_error("DB_VALIDATION: timeframe must be 20 characters or fewer")
        return None

    if not normalized.isalnum():
        display.print_error("DB_VALIDATION: timeframe must be alphanumeric")
        return None

    return normalized


def validate_nullable_float(value: Optional[float], field: str) -> bool:
    """Validate that a value is either None or a valid float."""
    if value is None:
        return True
    if not isinstance(value, (int, float)):
        display.print_error(f"DB_VALIDATION: {field} must be a number or None")
        return False
    return True


def validate_aoi(aoi: dict) -> bool:
    """Validate area of interest bounds."""
    lower = aoi.get("lower_bound")
    upper = aoi.get("upper_bound")
    if not validate_nullable_float(lower, "lower_bound"):
        return False
    if not validate_nullable_float(upper, "upper_bound"):
        return False
    return True