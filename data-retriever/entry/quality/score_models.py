"""Data models for entry signal quality scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class StageScore:
    """Individual stage score data for DB insertion."""
    stage_name: str      # 'S1', 'S2', ..., 'S8'
    raw_score: float     # 0.0 to 1.0
    weight: float        # stage weight
    weighted_score: float  # raw_score * weight


@dataclass
class QualityResult:
    """Complete quality evaluation result."""
    final_score: float
    tier: str  # 'NONE', 'WATCHLIST', 'NOTIFY', 'PRIORITY'
    stage_scores: List[StageScore]
