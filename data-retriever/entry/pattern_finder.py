from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Union

import pandas as pd

from entry.models import EntryPattern
from models import AOIZone, TrendDirection
from models.market import Candle
from utils.candles import prepare_candles

__all__ = ["find_entry_pattern"]


def find_entry_pattern(
    candles: Union[pd.DataFrame, Sequence[Union[Candle, Mapping[str, Any]]]],
    aoi: AOIZone,
    direction: TrendDirection,
) -> Optional[EntryPattern]:
    """Return the entry pattern for the given AOI and direction, if any."""
    direction = TrendDirection.from_raw(direction)
    if direction is None:
        return None

    prepared_candles = prepare_candles(candles, limit=15, sort_by_time=True)
    if direction == TrendDirection.BEARISH:
        return _find_bearish_pattern(prepared_candles, aoi)
    return _find_bullish_pattern(prepared_candles, aoi)


def _find_bearish_pattern(candles: List[Candle], aoi: AOIZone) -> Optional[EntryPattern]:
    last_candle = candles[-1]
    is_break_candle_last = False
    if _is_bearish_break(last_candle, aoi):
        break_idx = len(candles) - 1
        is_break_candle_last = True
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
        distance_between_last_candle_to_retest_candle = len(candles) - 1 - idx
        if (
            candle.open < aoi.lower
            and candle.close >= aoi.lower
            and distance_between_last_candle_to_retest_candle > 1
        ):
            return EntryPattern(
                direction=TrendDirection.BEARISH,
                aoi=aoi,
                candles=candles[idx:],
                is_break_candle_last=is_break_candle_last,
            )
    return None


def _find_bullish_pattern(candles: List[Candle], aoi: AOIZone) -> Optional[EntryPattern]:
    last_candle = candles[-2]
    is_break_candle_last = False
    if _is_bullish_break(last_candle, aoi):
        break_idx = len(candles) - 2
        is_break_candle_last = True
    elif _is_fully_above_aoi(last_candle, aoi):
        break_idx = len(candles) - 3
        if break_idx < 0 or not _is_bullish_break(candles[break_idx], aoi):
            return None
    else:
        return None

    for idx in range(break_idx - 1, -1, -1):
        candle = candles[idx]
        if _opens_inside_aoi(candle, aoi) and _closes_below_aoi(candle, aoi):
            return None
        distance_between_last_candle_to_retest_candle = len(candles) - 1 - idx
        if (
            candle.open > aoi.upper
            and candle.close <= aoi.upper
            and distance_between_last_candle_to_retest_candle > 1
        ):
            return EntryPattern(
                direction=TrendDirection.BULLISH,
                aoi=aoi,
                candles=candles[idx:],
                is_break_candle_last=is_break_candle_last,
            )
    return None


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
