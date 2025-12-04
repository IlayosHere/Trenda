from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Mapping


class TrendDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"

    @classmethod
    def from_raw(cls, raw: Any) -> "TrendDirection | None":
        """Normalize raw trend input from strings or mappings into an enum value."""

        if isinstance(raw, Mapping):
            raw = raw.get("trend")

        if isinstance(raw, cls):
            return raw

        if isinstance(raw, str):
            try:
                return cls(raw.lower())
            except ValueError:
                return None

        return None


@dataclass
class AOIZone:
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            self.lower, self.upper = self.upper, self.lower


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Candle":
        return cls(
            time=data.get("time"),
            open=float(data.get("open")),
            high=float(data.get("high")),
            low=float(data.get("low")),
            close=float(data.get("close")),
        )


@dataclass
class SignalData:
    candles: List[Candle]
    signal_time: datetime
    trade_quality: float

