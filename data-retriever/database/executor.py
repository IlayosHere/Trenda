import os
import time
from typing import Any, Callable, Iterable, Optional, Sequence, TypeVar, Union

from psycopg2.extensions import cursor as PgCursor

from .connection import DBConnectionManager, log
from psycopg2 import InterfaceError, OperationalError
from psycopg2.extensions import connection as PgConnection

_T = TypeVar("_T")

MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("DB_RETRY_DELAY", "0.5"))


class DBDoNotRetryError(Exception):
    """Raised for errors that should never be retried (e.g., constraint violations)."""


def _truncate_sql(sql: str, limit: int = 150) -> str:
    return sql if len(sql) <= limit else f"{sql[:limit]}...(truncated)"


def _log_sql_error(context: str, sql: str, params: Optional[Sequence[Any]], exc: Exception) -> None:
    log.error(
        "DB_ERROR|context=%s|sql=%s|params=%s|error=%s",
        context,
        _truncate_sql(sql),
        params,
        exc,
        exc_info=True,
    )


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True

    if hasattr(exc, "pgcode") and exc.pgcode:
        retryable_codes = [
            "40P01",
            "40001",
            "08000",
            "08001",
            "08003",
            "08004",
            "08006",
            "57P03",
        ]
        return exc.pgcode in retryable_codes

    return False


def _is_do_not_retry_error(exc: Exception) -> bool:
    if isinstance(exc, DBDoNotRetryError):
        return True

    if hasattr(exc, "pgcode") and exc.pgcode:
        non_retryable_prefixes = ["23", "42"]
        return any(exc.pgcode.startswith(prefix) for prefix in non_retryable_prefixes)

    return False


def _execute_with_retry(
    operation: Callable[[], _T], context: str = "", retry: bool = True, max_retries: int = MAX_RETRIES
) -> _T:
    if not retry:
        return operation()

    last_exception = None

    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as exc:
            last_exception = exc

            if _is_do_not_retry_error(exc):
                raise

            if not _is_retryable_error(exc) or attempt == max_retries - 1:
                raise

            delay = RETRY_DELAY * (2**attempt)
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
    if params is None or not isinstance(params, (list, tuple)):
        raise ValueError("Batch parameters must be a list or tuple")

    for idx, param_set in enumerate(params):
        if not isinstance(param_set, (list, tuple)):
            raise ValueError(f"Batch parameter set at index {idx} must be a list or tuple")


def _execute_sql(cursor: PgCursor, sql: str, params: Optional[Sequence[Any]] = None, many: bool = False) -> None:
    if many:
        cursor.executemany(sql, params)
    else:
        cursor.execute(sql, params)


def _fetch_results(cursor: PgCursor, fetch: Optional[str]) -> Any:
    if fetch == "one":
        return cursor.fetchone()
    elif fetch == "all":
        rows = cursor.fetchall()
        return rows if rows is not None else []
    else:
        return True


class DBExecutor:
    @classmethod
    def _execute(
        cls,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        fetch: Optional[str] = None,
        many: bool = False,
        cursor_factory: Optional[Callable[..., PgCursor]] = None,
        context: str = "",
        retry: bool = True,
    ) -> Any:
        def operation():
            conn: Optional[PgConnection] = None
            error: Optional[Exception] = None

            try:
                conn = DBConnectionManager.get_connection()

                if many:
                    _validate_batch_params(params)

                # 'with conn:' context manager handles transaction:
                # - Commits automatically on successful exit
                # - Rolls back automatically on exception
                # This ensures atomicity - either all rows succeed or all fail
                # Note: psycopg2 connections have autocommit=False by default
                with conn:
                    with conn.cursor(cursor_factory=cursor_factory) as cursor:
                        _execute_sql(cursor, sql, params, many)
                        result = _fetch_results(cursor, fetch)
                    # Commit happens automatically here on successful exit

                return result

            except Exception as exc:
                error = exc
                _log_sql_error(context, sql, params, exc)
                raise
            finally:
                if conn is not None:
                    DBConnectionManager._release_connection_safely(conn, error)

        return _execute_with_retry(operation, context=context, retry=retry)

    @classmethod
    def execute_non_query(
        cls, sql: str, params: Optional[Sequence[Any]] = None, context: str = "non_query", retry: bool = True
    ) -> bool:
        return bool(
            cls._execute(sql, params=params, fetch=None, context=context, retry=retry)
        )

    @classmethod
    def execute_many(
        cls,
        sql: str,
        param_sets: Iterable[Sequence[Any]],
        context: str = "batch",
        retry: bool = True,
    ) -> bool:
        params_list: Union[Iterable[Sequence[Any]], list[Sequence[Any]]]
        if isinstance(param_sets, (list, tuple)):
            params_list = param_sets
        else:
            params_list = list(param_sets)
        return bool(
            cls._execute(sql, params=params_list, many=True, context=context, retry=retry)
        )

    @classmethod
    def fetch_one(
        cls,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        cursor_factory: Optional[Callable[..., PgCursor]] = None,
        context: str = "fetch_one",
        retry: bool = True,
    ) -> Optional[Any]:
        return cls._execute(
            sql,
            params=params,
            fetch="one",
            cursor_factory=cursor_factory,
            context=context,
            retry=retry,
        )

    @classmethod
    def fetch_all(
        cls,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        cursor_factory: Optional[Callable[..., PgCursor]] = None,
        context: str = "fetch_all",
        retry: bool = True,
    ) -> list[Any]:
        return cls._execute(
            sql,
            params=params,
            fetch="all",
            cursor_factory=cursor_factory,
            context=context,
            retry=retry,
        )

    @classmethod
    def execute_transaction(
        cls,
        work: Callable[[PgCursor], _T],
        context: str = "transaction",
        cursor_factory: Optional[Callable[..., PgCursor]] = None,
        retry: bool = True,
    ) -> _T:
        def operation():
            conn: Optional[PgConnection] = None
            error: Optional[Exception] = None

            try:
                conn = DBConnectionManager.get_connection()

                # 'with conn:' context manager handles transaction:
                # - Commits automatically on successful exit
                # - Rolls back automatically on exception
                # Note: psycopg2 connections have autocommit=False by default
                with conn:
                    with conn.cursor(cursor_factory=cursor_factory) as cursor:
                        result = work(cursor)
                    # Commit happens automatically here on successful exit
                    return result

            except Exception as exc:
                error = exc
                _log_sql_error(context, "<transaction>", None, exc)
                raise
            finally:
                if conn is not None:
                    DBConnectionManager._release_connection_safely(conn, error)

        return _execute_with_retry(operation, context=context, retry=retry)
