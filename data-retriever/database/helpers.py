from typing import Any



def value_from_candle(candle: Any, key: str):
    if hasattr(candle, key):
        return getattr(candle, key)
    if isinstance(candle, dict):
        return candle.get(key)
    raise TypeError("Unsupported candle type for storage")
