from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from models.market import AOIZone, Candle, TrendDirection


@dataclass
class EntryPattern:
    direction: TrendDirection
    aoi: AOIZone
    candles: list[Candle]
    is_break_candle_last: bool


LLMEvaluation = Mapping[str, Any]
