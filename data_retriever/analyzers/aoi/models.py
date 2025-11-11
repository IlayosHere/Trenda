"""Dataclasses used across the AOI analysis pipeline."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class AOIContext:
    symbol: str
    base_low: float
    base_high: float
    pip_size: float
    base_range_pips: float
    min_height_price: float
    max_height_price: float
    tolerance_price: float
    params: Dict[str, float]


@dataclass
class AOIZoneCandidate:
    lower_bound: float
    upper_bound: float
    height: float
    touches: int
    score: float
    last_swing_idx: int


__all__ = ["AOIContext", "AOIZoneCandidate"]
