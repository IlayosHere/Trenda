"""Trend access helpers for AOI analysis."""

from typing import Optional

from data_retriever.externals import db_handler


def determine_trend(symbol: str, timeframe: str) -> Optional[str]:
    """Return persisted trend bias for the given symbol and timeframe."""
    return db_handler.fetch_trend_bias(symbol, timeframe)


__all__ = ["determine_trend"]
