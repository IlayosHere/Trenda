"""Signal gates for production entry detection.

Gates filter signals BEFORE storing them to ensure only high-quality
setups are persisted. Each gate is a hard pass/fail check.

Gate 1 — Time filter: 22:00-12:00 UTC (wraps around midnight)
Gate 2 — Timeframe conflict: Exclude signals where conflicted_tf == '4H'
Gate 3 — HTF range alignment: Bullish ≤0.33 daily/≤0.50 weekly, Bearish ≥0.67/≥0.50
Gate 4 — Obstacle clearance: distance_to_next_htf_obstacle_atr >= 1.0
"""

from .validator import check_all_gates, GATES
from .models import Gate, GateContext, GateResult, GateCheckResult
from .time_of_day import TimeOfDayGate
from .timeframe_conflict import TimeframeConflictGate
from .htf_alignment import HTFAlignmentGate
from .obstacle_clearance import ObstacleClearanceGate

__all__ = [
    # Main function
    "check_all_gates",
    "GATES",
    # Gate protocol
    "Gate",
    "GateContext",
    "GateResult",
    "GateCheckResult",
    # Gate implementations
    "TimeOfDayGate",
    "TimeframeConflictGate",
    "HTFAlignmentGate",
    "ObstacleClearanceGate",
]

