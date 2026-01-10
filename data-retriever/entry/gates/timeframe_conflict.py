"""Gate 2: Timeframe conflict filter.

Excludes signals where conflicted_tf == '4H'.
"""

from .config import EXCLUDED_CONFLICTED_TF
from .models import Gate, GateContext, GateResult


class TimeframeConflictGate(Gate):
    """Gate 2: Timeframe conflict filter."""
    
    @property
    def name(self) -> str:
        return "Gate 2 - Timeframe Conflict"
    
    def check(self, ctx: GateContext) -> GateResult:
        # No conflict = all 3 TFs aligned = pass
        if ctx.conflicted_tf is None:
            return GateResult(passed=True, gate_name=self.name)
        
        # Check if the conflicted TF is the excluded one
        if ctx.conflicted_tf == EXCLUDED_CONFLICTED_TF:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason=f"{EXCLUDED_CONFLICTED_TF} timeframe conflicts with trade direction",
            )
        
        # Other conflicts (e.g., 1W) are allowed
        return GateResult(passed=True, gate_name=self.name)
