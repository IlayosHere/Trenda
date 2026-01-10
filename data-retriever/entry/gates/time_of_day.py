"""Time-of-day filter gate - ensures signals only during trading hours."""

from .models import Gate, GateContext, GateResult
from utils.trading_hours import TRADING_HOURS


class TimeOfDayGate(Gate):
    """Gate 1: Time-of-day filter.
    
    Ensures signals are only generated during configured trading hours (UTC).
    Uses the same TRADING_HOURS from utils/trading_hours.py for consistency.
    """
    
    @property
    def name(self) -> str:
        return "TimeOfDayGate"
    
    def check(self, ctx: GateContext) -> GateResult:
        # Ensure signal_time is timezone-aware and get UTC hour
        signal_time = ctx.signal_time
        
        # Handle both aware and naive datetimes
        if signal_time.tzinfo is not None:
            # Convert to UTC if needed
            from datetime import timezone
            utc_time = signal_time.astimezone(timezone.utc)
            hour_utc = utc_time.hour
        else:
            # Assume naive datetime is already UTC
            hour_utc = signal_time.hour
        
        if hour_utc not in TRADING_HOURS:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason=f"Signal at {hour_utc}:00 UTC is outside trading hours (allowed: 22-23, 0-12 UTC)",
            )
        
        return GateResult(passed=True, gate_name=self.name)

