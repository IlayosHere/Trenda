"""HTF Range Score calculation.

Score daily and weekly HTF range positions separately, then average them.

Uses threshold tuples from config for scoring.
"""

from typing import Tuple

from models import TrendDirection

from entry.gates.config import (
    BULLISH_SCORE_THRESHOLDS,
    BEARISH_SCORE_THRESHOLDS,
)


def _score_from_thresholds(
    position: float, 
    thresholds: Tuple[Tuple[float, float], ...], 
    is_bullish: bool,
) -> float:
    """
    Compute score based on position and direction-specific thresholds.
    
    Args:
        position: HTF range position (0-1)
        thresholds: Tuple of (threshold, score) pairs
        is_bullish: True for bullish (position <= threshold), False for bearish (position >= threshold)
        
    Returns:
        Score from 0-3
    """
    for threshold, score in thresholds:
        if is_bullish:
            if position <= threshold:
                return score
        else:
            if position >= threshold:
                return score
    return 0.0


def compute_single_htf_score(position: float, direction: TrendDirection) -> float:
    """
    Compute score for a single HTF range position.
    
    Args:
        position: HTF range position (0-1)
        direction: Trade direction
        
    Returns:
        Score from 0-3
    """
    is_bullish = direction == TrendDirection.BULLISH
    thresholds = BULLISH_SCORE_THRESHOLDS if is_bullish else BEARISH_SCORE_THRESHOLDS
    return _score_from_thresholds(position, thresholds, is_bullish)


def compute_htf_range_score(
    direction: TrendDirection,
    htf_range_position_daily: float,
    htf_range_position_weekly: float,
) -> Tuple[float, float, float]:
    """
    Compute HTF range score averaged across daily and weekly.
    
    Args:
        direction: Trade direction
        htf_range_position_daily: Position within daily range (0-1)
        htf_range_position_weekly: Position within weekly range (0-1)
        
    Returns:
        Tuple of (htf_score, daily_score, weekly_score)
    """
    daily_score = compute_single_htf_score(htf_range_position_daily, direction)
    weekly_score = compute_single_htf_score(htf_range_position_weekly, direction)
    
    htf_score = (daily_score + weekly_score) / 2.0
    
    return htf_score, daily_score, weekly_score
