"""Gate 4: Obstacle clearance check.

Distance to next HTF obstacle must be >= 1.0 ATR.
"""

from .config import MIN_OBSTACLE_DISTANCE_ATR
from .models import Gate, GateContext, GateResult


class ObstacleClearanceGate(Gate):
    """Gate 4: Obstacle clearance check."""
    
    @property
    def name(self) -> str:
        return "Gate 4 - Obstacle Clearance"
    
    def check(self, ctx: GateContext) -> GateResult:
        distance = ctx.distance_to_next_htf_obstacle_atr
        
        if distance is None:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason="Distance to HTF obstacle is NULL",
            )
        
        if distance < MIN_OBSTACLE_DISTANCE_ATR:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason=f"Obstacle at {distance:.2f} ATR, minimum {MIN_OBSTACLE_DISTANCE_ATR} required",
            )
        
        return GateResult(passed=True, gate_name=self.name)
