"""Signal outcome computation module.

Computes post-signal market behavior for entry signals.
"""

from .outcome_processor import run_signal_outcome_processor

__all__ = ["run_signal_outcome_processor"]
