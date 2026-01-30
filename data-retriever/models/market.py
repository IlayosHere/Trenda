from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Mapping, Optional


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
        from datetime import timezone
        
        # Handle pandas Timestamp first
        if hasattr(value, "to_pydatetime"):
            # Convert pandas Timestamp to datetime, preserving timezone
            dt = value.to_pydatetime()
            # If timezone-aware, convert to UTC
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc)
            # If naive, assume it's already UTC
            return dt.replace(tzinfo=timezone.utc)
        
        if isinstance(value, datetime):
            # If timezone-aware, convert to UTC
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc)
            # If naive, assume it's already UTC
            return value.replace(tzinfo=timezone.utc)

        if isinstance(value, (int, float)):
            # Unix timestamp - always interpret as UTC
            return datetime.fromtimestamp(value, tz=timezone.utc)

        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is not None:
                    return dt.astimezone(timezone.utc)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        raise TypeError("Candle time value must be datetime-compatible")


@dataclass
class SignalData:
    """Complete signal data for database insertion.
    
    Note: entry_price, sl_distance_atr, tp_distance_atr, actual_rr, price_drift
    are populated after live execution with real-time prices.
    """
    # Candle context
    candles: List[Candle]
    signal_time: datetime
    direction: TrendDirection
    # AOI snapshot (simplified)
    aoi_timeframe: str
    aoi_low: float
    aoi_high: float
    # Entry context (populated after live execution)
    entry_price: Optional[float]  # Live execution price
    atr_1h: float
    # New scoring system
    htf_score: float
    obstacle_score: float
    total_score: float
    # SL/TP configuration (calculated with signal candle close)
    sl_model: str
    sl_distance_atr: Optional[float]  # Calculated based on signal candle close
    tp_distance_atr: Optional[float]  # Calculated based on signal candle close
    rr_multiple: float
    actual_rr: Optional[float] = None  # Actual R:R from execution price perspective
    price_drift: Optional[float] = None  # Price movement from signal candle to execution
    # Meta
    is_break_candle_last: bool = False
    # HTF context for reference
    htf_range_position_daily: Optional[float] = None
    htf_range_position_weekly: Optional[float] = None
    distance_to_next_htf_obstacle_atr: Optional[float] = None
    conflicted_tf: Optional[str] = None
