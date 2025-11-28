from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Mapping, Optional, Sequence, Union

import pandas as pd

from configuration import ANALYSIS_PARAMS, FOREX_PAIRS, TIMEFRAMES
import externals.db_handler as db_handler
from externals.data_fetcher import fetch_data
import utils.display as display
from analyzers.trend import get_trend_by_timeframe


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


DEFAULT_TREND_ALIGNMENT: tuple[str, ...] = ("4H", "1D", "1W")


def run_1h_entry_scan_job(
    timeframe: str,
    trend_alignment_timeframes: Sequence[str] = DEFAULT_TREND_ALIGNMENT,
) -> List[dict]:
    """Scheduled 1H entry scan across all forex pairs and tradable AOIs."""

    mt5_timeframe = TIMEFRAMES.get(timeframe)
    lookback = ANALYSIS_PARAMS[timeframe].get("lookback")
    results: List[dict] = []

    display.print_status(f"\n--- 🔍 Running {timeframe} entry scan across symbols ---")

    for symbol in FOREX_PAIRS:
        display.print_status(f"  -> Checking {symbol}...")
        candles = fetch_data(symbol, mt5_timeframe, int(lookback))

        trend_snapshot = _collect_trend_snapshot(trend_alignment_timeframes, symbol)
        direction = _normalize_direction(
            _resolve_overall_trend(trend_alignment_timeframes, trend_snapshot)
        )
        if direction is None:
            continue

        aois = db_handler.fetch_tradable_aois(symbol)
        if not aois:
            continue

        for aoi_data in aois:
            lower = aoi_data.get("lower_bound")
            upper = aoi_data.get("upper_bound")
            aoi = AOIZone(lower=lower, upper=upper)
            signal = scan_1h_for_entry(symbol, direction, aoi, candles)
            if signal:
                results.append(signal)
                display.print_status(
                    f"    ✅ Entry signal found for {symbol} at AOI {aoi.lower}-{aoi.upper}."
                )
    return results

def _normalize_direction(raw: Optional[Union[str, Mapping[str, Any]]]) -> Optional[TrendDirection]:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        raw = raw.get("trend")
    if isinstance(raw, str):
        try:
            return TrendDirection(raw.lower())
        except ValueError:
            return None
    return None

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

    entry_id = db_handler.store_entry_signal(
        symbol=symbol,
        trend_snapshot=trend_snapshot,
        aoi_high=aoi.upper,
        aoi_low=aoi.lower,
        signal_time=break_candle.time,
        candles=pattern.candles,
    )

    return {
        "entry_id": entry_id,
        "symbol": symbol,
        "direction": direction.value,
        "aoi": {"lower": aoi.lower, "upper": aoi.upper},
        "break_time": break_candle.time,
        "retest_time": retest_candle.time,
        "confidence": evaluation.get("confidence"),
        "reason": evaluation.get("reason"),
    }
    
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


def _collect_trend_snapshot(
    timeframes: Sequence[str], symbol: str
) -> Mapping[str, Optional[str]]:
    return {tf: get_trend_by_timeframe(symbol, tf) for tf in timeframes}


def _resolve_overall_trend(
    timeframes: Sequence[str], trend_snapshot: Mapping[str, Optional[str]]
) -> Optional[str]:
    trend_values = [
        {"trend": trend_snapshot.get(tf), "timeframe": tf} for tf in timeframes
    ]

    if not trend_values or any(tv["trend"] is None for tv in trend_values):
        return None

    if len(trend_values) >= 3:
        if (
            trend_values[0]["trend"] == trend_values[1]["trend"]
            or trend_values[1]["trend"] == trend_values[2]["trend"]
        ):
            return trend_values[1]["trend"]
        return None

    if len(trend_values) >= 2 and trend_values[0]["trend"] == trend_values[1]["trend"]:
        return trend_values[0]["trend"]

    return None

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
    last_candle = candles[-1]
    
    if _is_bearish_break(last_candle, aoi):
        break_idx = len(candles) - 1
    elif _is_fully_below_aoi(last_candle, aoi):
        break_idx = len(candles) - 2
        if break_idx < 0 or not _is_bearish_break(candles[break_idx], aoi):
            return None
    else:
        return None

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
    last_candle = candles[-1]

    if _is_bullish_break(last_candle, aoi):
        break_idx = len(candles) - 1
    elif _is_fully_above_aoi(last_candle, aoi):
        break_idx = len(candles) - 2
        if break_idx < 0 or not _is_bullish_break(candles[break_idx], aoi):
            return None
    else:
        return None

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


def _is_fully_below_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return candle.high < aoi.lower


def _is_fully_above_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return min(candle.open, candle.high, candle.low, candle.close) > aoi.upper


def _is_bearish_break(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close < aoi.lower and aoi.lower <= candle.open <= aoi.upper


def _is_bullish_break(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close > aoi.upper and aoi.lower <= candle.open <= aoi.upper


def _opens_inside_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return aoi.lower <= candle.open <= aoi.upper


def _closes_above_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close > aoi.upper


def _closes_below_aoi(candle: Candle, aoi: AOIZone) -> bool:
    return candle.close < aoi.lower