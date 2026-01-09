"""Signal scoring system for production entry detection.

Scoring is applied AFTER gates pass. The total score must be >= 4.0.

Components:
- HTF Range Score: 0-3 (averaged across daily/weekly)
- Obstacle Score: Fixed 3.0 (gate already ensures >= 1.0 ATR)
"""

from .calculator import calculate_score
from .models import ScoreResult

__all__ = [
    "calculate_score",
    "ScoreResult",
]
