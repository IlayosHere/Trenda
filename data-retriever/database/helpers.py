from typing import Any, Mapping, Optional


def required_trend(trend_snapshot: Mapping[str, Optional[str]], timeframe: str) -> str:
    value = trend_snapshot.get(timeframe)
    if value is None:
        raise ValueError(f"Missing trend for timeframe {timeframe}")
    return value


def value_from_candle(candle: Any, key: str):
    if hasattr(candle, key):
        return getattr(candle, key)
    if isinstance(candle, dict):
        return candle.get(key)
    raise TypeError("Unsupported candle type for storage")
