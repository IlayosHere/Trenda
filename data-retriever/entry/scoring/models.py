"""Score result dataclass."""

from dataclasses import dataclass


@dataclass
class ScoreResult:
    """Result of score calculation."""
    htf_score: float
    obstacle_score: float
    total_score: float
    passed: bool
    
    # Component details
    daily_score: float
    weekly_score: float
