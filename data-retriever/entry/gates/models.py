"""Gate models and protocol for signal filtering."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class GateResult:
    """Result of a single gate evaluation."""
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


@dataclass
class GateContext:
    """Context data passed to all gates."""
    signal_time: Any  # datetime
    symbol: str
    direction: Any  # TrendDirection
    conflicted_tf: Optional[str]
    htf_range_position_daily: Optional[float]
    htf_range_position_weekly: Optional[float]
    distance_to_next_htf_obstacle_atr: Optional[float]


class Gate(ABC):
    """Abstract base class for signal gates."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Gate name for logging."""
        pass
    
    @abstractmethod
    def check(self, ctx: GateContext) -> GateResult:
        """Check if signal passes this gate."""
        pass
