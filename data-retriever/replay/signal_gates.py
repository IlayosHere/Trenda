"""Signal gates for replay mode.

Gates filter signals BEFORE storing them to ensure only high-quality
setups are persisted. Each gate is a hard pass/fail check.

Gate 1 — Day policy: Mon-Thu only
Gate 2 — Time policy: 04:00-13:00 UTC
Gate 3 — HTF room: distance_to_next_htf_obstacle_atr >= 2.0
Gate 4 — Range position: bullish <= 0.40, bearish >= 0.60
Gate 5 — Trend maturity: trend_age_bars_1h < 80
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from models import TrendDirection

from .pre_entry_context_v2 import PreEntryContextV2Data


# =============================================================================
# Gate Configuration Constants
# =============================================================================

# Gate 1: Allowed days (0=Monday, 4=Friday, 5=Saturday, 6=Sunday)
ALLOWED_DAYS = {0, 1, 2, 3}  # Monday through Thursday

# Gate 2: Trading hours (UTC, inclusive)
TRADING_HOUR_START = 4   # 04:00 UTC
TRADING_HOUR_END = 13    # 13:00 UTC

# Gate 3: Minimum room to next obstacle (ATR)
MIN_HTF_OBSTACLE_ATR = 2.0

# Gate 4: Range position thresholds
MAX_BULLISH_RANGE_POSITION = 0.40
MIN_BEARISH_RANGE_POSITION = 0.60

# Gate 5: Trend maturity limit
MAX_TREND_AGE_BARS = 80


@dataclass
class GateResult:
    """Result of gate evaluation."""
    passed: bool
    gate_name: str
    reason: Optional[str] = None


@dataclass
class GateCheckResult:
    """Combined result of all gate checks."""
    passed: bool
    failed_gate: Optional[str] = None
    failed_reason: Optional[str] = None
    
    @staticmethod
    def success() -> "GateCheckResult":
        return GateCheckResult(passed=True)
    
    @staticmethod
    def failure(gate_name: str, reason: str) -> "GateCheckResult":
        return GateCheckResult(
            passed=False,
            failed_gate=gate_name,
            failed_reason=reason,
        )


def check_all_gates(
    signal_time: datetime,
    direction: TrendDirection,
    context_v2: PreEntryContextV2Data,
) -> GateCheckResult:
    """
    Run all gates on a signal. Returns immediately on first failure.
    
    Args:
        signal_time: Signal timestamp (must be timezone-aware UTC)
        direction: Trade direction
        context_v2: Pre-entry context V2 data with computed metrics
        
    Returns:
        GateCheckResult indicating pass/fail and reason if failed
    """
    # Gate 1 — Day Policy
    result = _check_day_policy(signal_time)
    if not result.passed:
        return GateCheckResult.failure(result.gate_name, result.reason)
    
    # Gate 2 — Time Policy
    result = _check_time_policy(signal_time)
    if not result.passed:
        return GateCheckResult.failure(result.gate_name, result.reason)
    
    # Gate 3 — HTF Room to Obstacle
    result = _check_htf_obstacle_room(context_v2)
    if not result.passed:
        return GateCheckResult.failure(result.gate_name, result.reason)
    
    # Gate 4 — Range Position
    result = _check_range_position(direction, context_v2)
    if not result.passed:
        return GateCheckResult.failure(result.gate_name, result.reason)
    
    # Gate 5 — Trend Maturity
    result = _check_trend_maturity(context_v2)
    if not result.passed:
        return GateCheckResult.failure(result.gate_name, result.reason)
    
    return GateCheckResult.success()


def _check_day_policy(signal_time: datetime) -> GateResult:
    """Gate 1: Trade only Mon-Thu."""
    weekday = signal_time.weekday()  # 0=Monday, 6=Sunday
    
    if weekday not in ALLOWED_DAYS:
        day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", 
                   "Friday", "Saturday", "Sunday"][weekday]
        return GateResult(
            passed=False,
            gate_name="Gate 1 - Day Policy",
            reason=f"Signal on {day_name}, only Mon-Thu allowed",
        )
    
    return GateResult(passed=True, gate_name="Gate 1 - Day Policy")


def _check_time_policy(signal_time: datetime) -> GateResult:
    """Gate 2: Trade only 04:00-13:00 UTC."""
    hour = signal_time.hour
    
    if hour < TRADING_HOUR_START or hour > TRADING_HOUR_END:
        return GateResult(
            passed=False,
            gate_name="Gate 2 - Time Policy",
            reason=f"Signal at {hour:02d}:00 UTC, only 04:00-13:00 allowed",
        )
    
    return GateResult(passed=True, gate_name="Gate 2 - Time Policy")


def _check_htf_obstacle_room(context_v2: PreEntryContextV2Data) -> GateResult:
    """Gate 3: distance_to_next_htf_obstacle_atr >= 2.0."""
    obstacle_atr = context_v2.distance_to_next_htf_obstacle_atr
    
    if obstacle_atr is None:
        return GateResult(
            passed=False,
            gate_name="Gate 3 - HTF Obstacle Room",
            reason="distance_to_next_htf_obstacle_atr is NULL",
        )
    
    if obstacle_atr < MIN_HTF_OBSTACLE_ATR:
        return GateResult(
            passed=False,
            gate_name="Gate 3 - HTF Obstacle Room",
            reason=f"Obstacle at {obstacle_atr:.2f} ATR, minimum {MIN_HTF_OBSTACLE_ATR} required",
        )
    
    return GateResult(passed=True, gate_name="Gate 3 - HTF Obstacle Room")


def _check_range_position(
    direction: TrendDirection,
    context_v2: PreEntryContextV2Data,
) -> GateResult:
    """Gate 4: Bullish <= 0.40, Bearish >= 0.60."""
    position = context_v2.htf_range_position_daily
    
    if position is None:
        return GateResult(
            passed=False,
            gate_name="Gate 4 - Range Position",
            reason="htf_range_position_daily is NULL",
        )
    
    is_bullish = direction == TrendDirection.BULLISH
    
    if is_bullish and position > MAX_BULLISH_RANGE_POSITION:
        return GateResult(
            passed=False,
            gate_name="Gate 4 - Range Position",
            reason=f"Bullish at {position:.2f} range position, max {MAX_BULLISH_RANGE_POSITION} allowed",
        )
    
    if not is_bullish and position < MIN_BEARISH_RANGE_POSITION:
        return GateResult(
            passed=False,
            gate_name="Gate 4 - Range Position",
            reason=f"Bearish at {position:.2f} range position, min {MIN_BEARISH_RANGE_POSITION} required",
        )
    
    return GateResult(passed=True, gate_name="Gate 4 - Range Position")


def _check_trend_maturity(context_v2: PreEntryContextV2Data) -> GateResult:
    """Gate 5: trend_age_bars_1h < 80."""
    age = context_v2.trend_age_bars_1h
    
    if age is None:
        # NULL age is acceptable (trend just started or not measurable)
        return GateResult(passed=True, gate_name="Gate 5 - Trend Maturity")
    
    if age >= MAX_TREND_AGE_BARS:
        return GateResult(
            passed=False,
            gate_name="Gate 5 - Trend Maturity",
            reason=f"Trend age {age} bars, max {MAX_TREND_AGE_BARS - 1} allowed",
        )
    
    return GateResult(passed=True, gate_name="Gate 5 - Trend Maturity")
