"""Main gate checker - runs all gates in sequence using Gate protocol."""

from datetime import datetime
from typing import List, Optional, Type

from models import TrendDirection

from .models import Gate, GateContext, GateCheckResult
from .time_of_day import TimeOfDayGate
from .timeframe_conflict import TimeframeConflictGate
from .htf_alignment import HTFAlignmentGate
from .obstacle_clearance import ObstacleClearanceGate


# Ordered list of gate classes to run
GATES: List[Type[Gate]] = [
    TimeOfDayGate,  # Gate 1: Time filter (22-12 UTC)
    TimeframeConflictGate,  # Gate 2: 4H conflict check
    HTFAlignmentGate,  # Gate 3: Range position check
    ObstacleClearanceGate,  # Gate 4: Obstacle distance check
]


def check_all_gates(
    signal_time: datetime,
    symbol: str,
    direction: TrendDirection,
    conflicted_tf: Optional[str],
    htf_range_position_daily: Optional[float],
    htf_range_position_weekly: Optional[float],
    distance_to_next_htf_obstacle_atr: Optional[float],
) -> GateCheckResult:
    """
    Run all gates on a signal. Returns immediately on first failure.
    
    Args:
        signal_time: Signal timestamp (must be timezone-aware UTC)
        symbol: Trading symbol
        direction: Trade direction
        conflicted_tf: The conflicted timeframe (None if all aligned)
        htf_range_position_daily: Position within daily range (0-1)
        htf_range_position_weekly: Position within weekly range (0-1)
        distance_to_next_htf_obstacle_atr: Distance to next obstacle in ATR units
        
    Returns:
        GateCheckResult indicating pass/fail and reason if failed
    """
    # Build context once, pass to all gates
    ctx = GateContext(
        signal_time=signal_time,
        symbol=symbol,
        direction=direction,
        conflicted_tf=conflicted_tf,
        htf_range_position_daily=htf_range_position_daily,
        htf_range_position_weekly=htf_range_position_weekly,
        distance_to_next_htf_obstacle_atr=distance_to_next_htf_obstacle_atr,
    )
    
    # Run each gate in sequence
    for gate_cls in GATES:
        gate = gate_cls()
        result = gate.check(ctx)
        if not result.passed:
            return GateCheckResult.failure(result.gate_name, result.reason)
    
    return GateCheckResult.success()
