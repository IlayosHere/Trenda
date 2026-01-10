"""Gate 3: HTF range alignment check.

Bullish: daily <= 0.33, weekly <= 0.50
Bearish: daily >= 0.67, weekly >= 0.50
"""

from typing import Optional

from models import TrendDirection

from .config import (
    MAX_BULLISH_DAILY_POSITION,
    MAX_BULLISH_WEEKLY_POSITION,
    MIN_BEARISH_DAILY_POSITION,
    MIN_BEARISH_WEEKLY_POSITION,
)
from .models import Gate, GateContext, GateResult


def _check_position_threshold(
    position: Optional[float],
    threshold: float,
    is_max: bool,
    label: str,
    direction_label: str,
) -> Optional[str]:
    """
    Check if position meets threshold requirement.
    
    Args:
        position: HTF range position (0-1)
        threshold: Threshold value
        is_max: If True, position must be <= threshold; else >= threshold
        label: Timeframe label (e.g., "daily")
        direction_label: Direction label (e.g., "Bullish")
        
    Returns:
        None if passed, error message if failed
    """
    if position is None:
        return f"{label.title()} HTF range position is NULL"
    
    if is_max:
        if position > threshold:
            return f"{direction_label} {label} position {position:.2f} > {threshold}"
    else:
        if position < threshold:
            return f"{direction_label} {label} position {position:.2f} < {threshold}"
    
    return None


class HTFAlignmentGate(Gate):
    """Gate 3: HTF range alignment check."""
    
    @property
    def name(self) -> str:
        return "Gate 3 - HTF Alignment"
    
    def check(self, ctx: GateContext) -> GateResult:
        is_bullish = ctx.direction == TrendDirection.BULLISH
        
        # Define checks based on direction
        if is_bullish:
            checks = [
                (ctx.htf_range_position_daily, MAX_BULLISH_DAILY_POSITION, True, "daily", "Bullish"),
                (ctx.htf_range_position_weekly, MAX_BULLISH_WEEKLY_POSITION, True, "weekly", "Bullish"),
            ]
        else:
            checks = [
                (ctx.htf_range_position_daily, MIN_BEARISH_DAILY_POSITION, False, "daily", "Bearish"),
                (ctx.htf_range_position_weekly, MIN_BEARISH_WEEKLY_POSITION, False, "weekly", "Bearish"),
            ]
        
        # Run all checks
        for position, threshold, is_max, label, direction_label in checks:
            error = _check_position_threshold(position, threshold, is_max, label, direction_label)
            if error:
                return GateResult(passed=False, gate_name=self.name, reason=error)
        
        return GateResult(passed=True, gate_name=self.name)
