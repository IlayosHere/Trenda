from typing import Any, Mapping, Optional

from models import TrendDirection


def required_trend(
    trend_snapshot: Mapping[str, Optional[TrendDirection]], timeframe: str
) -> str:
    value = trend_snapshot.get(timeframe)
    if value is None:
        raise ValueError(f"Missing trend for timeframe {timeframe}")

    direction = TrendDirection.from_raw(value)
    if direction is None:
        raise TypeError(f"Invalid trend value {value!r} for timeframe {timeframe}")

    return direction.value


def value_from_candle(candle: Any, key: str):
    if hasattr(candle, key):
        return getattr(candle, key)
    if isinstance(candle, dict):
        return candle.get(key)
    raise TypeError("Unsupported candle type for storage")
