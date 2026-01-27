"""Total score calculation.

total_score = htf_score + obstacle_score
Minimum threshold: MIN_TOTAL_SCORE from config
"""

from models import TrendDirection

from entry.gates.config import MIN_TOTAL_SCORE, FIXED_OBSTACLE_SCORE
from .htf_range_score import compute_htf_range_score
from .models import ScoreResult


def calculate_score(
    direction: TrendDirection,
    htf_range_position_daily: float,
    htf_range_position_weekly: float,
) -> ScoreResult:
    """
    Calculate total score and determine if it passes threshold.
    
    Args:
        direction: Trade direction
        htf_range_position_daily: Position within daily range (0-1)
        htf_range_position_weekly: Position within weekly range (0-1)
        
    Returns:
        ScoreResult with all scores and pass/fail status
    """
    # Calculate HTF range score
    htf_score, daily_score, weekly_score = compute_htf_range_score(
        direction,
        htf_range_position_daily,
        htf_range_position_weekly,
    )
    
    # Use fixed obstacle score directly
    obstacle_score = FIXED_OBSTACLE_SCORE
    
    # Total score
    total_score = htf_score + obstacle_score
    
    # Check threshold
    passed = total_score >= MIN_TOTAL_SCORE
    
    return ScoreResult(
        htf_score=htf_score,
        obstacle_score=obstacle_score,
        total_score=total_score,
        passed=passed,
        daily_score=daily_score,
        weekly_score=weekly_score,
    )
