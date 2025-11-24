"""Entry pattern detection for 1H break-and-retest setups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Mapping, Optional, Sequence, Union

import pandas as pd


class TrendDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


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
class EntryPattern:
    direction: TrendDirection
    aoi: AOIZone
    retest_index: int
    break_index: int
    candles: List[Candle]


LLMEvaluation = Mapping[str, Any]


def _is_fully_below_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return max(candle.open, candle.high, candle.low, candle.close) < aoi.lower


def _is_fully_above_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return min(candle.open, candle.high, candle.low, candle.close) > aoi.upper


def _is_intersecting_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return not (_is_fully_above_aoi(candle, aoi) or _is_fully_below_aoi(candle, aoi))


def _is_bearish_break(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close < aoi.lower and aoi.lower <= candle.high <= aoi.upper


def _is_bullish_break(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close > aoi.upper and aoi.lower <= candle.low <= aoi.upper


def _opens_inside_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return aoi.lower <= candle.open <= aoi.upper


def _closes_above_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close > aoi.upper


def _closes_below_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close < aoi.lower


def _prepare_candles(
    candles: Union[pd.DataFrame, Sequence[Union[Candle, Mapping[str, Any]]]]
) -> List[Candle]:
    if isinstance(candles, pd.DataFrame):
        df = candles
        if "time" in df.columns:
            df = df.sort_values("time")
        source = df.tail(15).to_dict(orient="records")
    else:
        source = list(candles)[-15:]
    prepared: List[Candle] = []
    for entry in source:
        if isinstance(entry, Candle):
            prepared.append(entry)
        elif isinstance(entry, Mapping):
            prepared.append(Candle.from_mapping(entry))
        else:
            raise TypeError("Unsupported candle input type")
    return prepared


def _find_bearish_pattern(candles: List[Candle], aoi: AOIZone) -> Optional[EntryPattern]:
    if len(candles) < 2:
        return None

    last_candle = candles[-1]
    if not (_is_fully_below_aoi(last_candle, aoi) or _is_bearish_break(last_candle, aoi)):
        return None

    if _is_bearish_break(last_candle, aoi):
        break_idx = len(candles) - 1
    else:
        if not _is_fully_below_aoi(last_candle, aoi):
            return None
        potential_break_idx = len(candles) - 2
        if potential_break_idx < 0 or not _is_bearish_break(candles[potential_break_idx], aoi):
            return None
        break_idx = potential_break_idx

    for idx in range(break_idx - 1, -1, -1):
        candle = candles[idx]
        if _opens_inside_aoi(candle, aoi) and _closes_above_aoi(candle, aoi):
            return None
        if candle.open < aoi.lower and candle.close >= aoi.lower:
            return EntryPattern(
                direction=TrendDirection.BEARISH,
                aoi=aoi,
                retest_index=idx,
                break_index=break_idx,
                candles=candles[idx : break_idx + 1],
            )
    return None


def _find_bullish_pattern(candles: List[Candle], aoi: AOIZone) -> Optional[EntryPattern]:
    if len(candles) < 2:
        return None

    last_candle = candles[-1]
    if not (_is_fully_above_aoi(last_candle, aoi) or _is_bullish_break(last_candle, aoi)):
        return None

    if _is_bullish_break(last_candle, aoi):
        break_idx = len(candles) - 1
    else:
        if not _is_fully_above_aoi(last_candle, aoi):
            return None
        potential_break_idx = len(candles) - 2
        if potential_break_idx < 0 or not _is_bullish_break(candles[potential_break_idx], aoi):
            return None
        break_idx = potential_break_idx

    for idx in range(break_idx - 1, -1, -1):
        candle = candles[idx]
        if _opens_inside_aoi(candle, aoi) and _closes_below_aoi(candle, aoi):
            return None
        if candle.open > aoi.upper and candle.close <= aoi.upper:
            return EntryPattern(
                direction=TrendDirection.BULLISH,
                aoi=aoi,
                retest_index=idx,
                break_index=break_idx,
                candles=candles[idx : break_idx + 1],
            )
    return None


def find_entry_pattern(
    candles: Union[pd.DataFrame, Sequence[Union[Candle, Mapping[str, Any]]]],
    aoi: AOIZone,
    direction: TrendDirection,
) -> Optional[EntryPattern]:
    if isinstance(direction, str):
        direction = TrendDirection(direction.lower())
    prepared_candles = _prepare_candles(candles)
    if direction == TrendDirection.BEARISH:
        return _find_bearish_pattern(prepared_candles, aoi)
    return _find_bullish_pattern(prepared_candles, aoi)


def evaluate_entry_with_llm(
    symbol: str,
    timeframe: str,
    direction: TrendDirection,
    aoi: AOIZone,
    pattern: EntryPattern,
) -> LLMEvaluation:
    return {
        "take_trade": True,
        "confidence": 1.0,
        "reason": "LLM stub approved the trade by default.",
    }


def scan_1h_for_entry(
    symbol: str,
    direction: TrendDirection,
    aoi: AOIZone,
    candles_1h: Union[pd.DataFrame, Sequence[Union[Candle, Mapping[str, Any]]]],
) -> Optional[dict]:
    if isinstance(direction, str):
        direction = TrendDirection(direction.lower())
    pattern = find_entry_pattern(candles_1h, aoi, direction)
    if not pattern:
        return None

    evaluation = evaluate_entry_with_llm(symbol, "1H", direction, aoi, pattern)
    if not evaluation.get("take_trade", False):
        return None

    relative_break_idx = pattern.break_index - pattern.retest_index
    break_candle = pattern.candles[relative_break_idx]
    retest_candle = pattern.candles[0]

    return {
        "symbol": symbol,
        "direction": direction.value,
        "aoi": {"lower": aoi.lower, "upper": aoi.upper},
        "break_time": break_candle.time,
        "retest_time": retest_candle.time,
        "confidence": evaluation.get("confidence"),
        "reason": evaluation.get("reason"),
    }
