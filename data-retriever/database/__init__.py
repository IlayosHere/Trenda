"""Database access layer consolidating connection, execution, and validation logic."""

from .connection import DBConnectionError, DBConnectionManager
from .executor import DBDoNotRetryError, DBExecutor
from .validation import DBValidator


def init_pool(minconn=None, maxconn=None):
    return DBConnectionManager.init_pool(minconn=minconn, maxconn=maxconn)


def get_connection():
    return DBConnectionManager.get_connection()


def close_pool():
    return DBConnectionManager.close_pool()


def get_pool_stats():
    return DBConnectionManager.get_pool_stats()


def execute_non_query(sql, params=None, context="non_query", retry=True):
    return DBExecutor.execute_non_query(sql, params=params, context=context, retry=retry)


def execute_many(sql, param_sets, context="batch", retry=True):
    return DBExecutor.execute_many(sql, param_sets, context=context, retry=retry)


def fetch_one(sql, params=None, cursor_factory=None, context="fetch_one", retry=True):
    return DBExecutor.fetch_one(
        sql,
        params=params,
        cursor_factory=cursor_factory,
        context=context,
        retry=retry,
    )


def fetch_all(sql, params=None, cursor_factory=None, context="fetch_all", retry=True):
    return DBExecutor.fetch_all(
        sql,
        params=params,
        cursor_factory=cursor_factory,
        context=context,
        retry=retry,
    )


def execute_transaction(work, context="transaction", cursor_factory=None, retry=True):
    return DBExecutor.execute_transaction(
        work, context=context, cursor_factory=cursor_factory, retry=retry
    )


def validate_symbol(symbol):
    return DBValidator.validate_symbol(symbol)


def validate_timeframe(timeframe):
    return DBValidator.validate_timeframe(timeframe)


def validate_nullable_float(value, field):
    return DBValidator.validate_nullable_float(value, field)


def validate_aoi(aoi):
    return DBValidator.validate_aoi(aoi)


__all__ = [
    "get_connection",
    "init_pool",
    "close_pool",
    "get_pool_stats",
    "execute_non_query",
    "execute_many",
    "fetch_one",
    "fetch_all",
    "execute_transaction",
    "validate_symbol",
    "validate_timeframe",
    "validate_nullable_float",
    "validate_aoi",
    "DBConnectionError",
    "DBDoNotRetryError",
    "DBExecutor",
    "DBConnectionManager",
    "DBValidator",
]
