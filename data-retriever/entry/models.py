from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from models import AOIZone, TrendDirection
from models.market import Candle


@dataclass
class EntryPattern:
    direction: TrendDirection
    aoi: AOIZone
    candles: list[Candle]
    is_break_candle_last: bool


LLMEvaluation = Mapping[str, Any]
