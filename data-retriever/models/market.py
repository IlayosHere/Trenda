from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Mapping


class TrendDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

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
    score: float | None = None
    touches: int | None = None
    last_swing_idx: int | None = None
    height: float | None = None
    classification: str | None = None
    timeframe: str | None = None

    def __post_init__(self) -> None:
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            self.lower, self.upper = self.upper, self.lower

    def with_classification(self, classification: str, score: float) -> "AOIZone":
        return AOIZone(
            lower=self.lower,
            upper=self.upper,
            score=score,
            touches=self.touches,
            last_swing_idx=self.last_swing_idx,
            height=self.height,
            classification=classification,
            timeframe=self.timeframe,
        )



@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Candle":
        time_value = cls._normalize_time(data.get("time"))

        return cls(
            time=time_value,
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
        )

    @staticmethod
    def _normalize_time(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value

        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime()  # type: ignore[no-any-return]

        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)

        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass

        raise TypeError("Candle time value must be datetime-compatible")


@dataclass
class SignalData:
    """Complete signal data for database insertion."""
    # Candle context
    candles: List[Candle]
    signal_time: datetime
    direction: TrendDirection
    # Trend snapshot
    trend_4h: str
    trend_1d: str
    trend_1w: str
    trend_alignment_strength: int
    # AOI snapshot
    aoi_timeframe: str
    aoi_low: float
    aoi_high: float
    aoi_classification: str
    # Entry context
    entry_price: float
    atr_1h: float
    # Scoring - imported from entry.quality to avoid circular imports
    quality_result: "QualityResult"  # Forward reference
    # Meta
    is_break_candle_last: bool
    # SL distances
    aoi_sl_tolerance_atr: float
    aoi_raw_sl_distance_price: float
    aoi_raw_sl_distance_atr: float
    aoi_effective_sl_distance_price: float
    aoi_effective_sl_distance_atr: float
