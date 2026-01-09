"""Obstacle score calculation.

Fixed at FIXED_OBSTACLE_SCORE since gate already ensures obstacle distance >= MIN_OBSTACLE_DISTANCE_ATR.
"""

from entry.gates.config import FIXED_OBSTACLE_SCORE


def compute_obstacle_score() -> float:
    """
    Compute obstacle score.
    
    Always returns FIXED_OBSTACLE_SCORE since the obstacle clearance gate already
    ensures the distance to next HTF obstacle is >= MIN_OBSTACLE_DISTANCE_ATR.
    
    Returns:
        Fixed score from config
    """
    return FIXED_OBSTACLE_SCORE
