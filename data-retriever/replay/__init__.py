"""Offline replay engine for re-simulating trading signals.

This package provides tools to replay historical market data candle-by-candle,
generating entry signals and outcomes exactly as they would have occurred in
real-time, without lookahead bias.

Usage:
    python -m replay.runner
    
    or in code:
    from replay.runner import run_replay
    run_replay()
"""

# Lazy imports to avoid circular import issues
# Import directly from submodules when needed:
#   from replay.runner import run_replay
#   from replay.config import REPLAY_SYMBOLS

__all__ = [
    # Config
    "REPLAY_SYMBOLS",
    "REPLAY_START_DATE",
    "REPLAY_END_DATE",
    "OUTCOME_WINDOW_BARS",
    "SCHEMA_NAME",
    # Runner
    "run_replay",
    "ReplayStats",
    # Components
    "CandleStore",
    "load_symbol_candles",
    "TimeframeAligner",
    "MarketStateManager",
    "SymbolState",
    "ReplaySignalDetector",
    "ReplayOutcomeCalculator",
]


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies."""
    if name in ("REPLAY_SYMBOLS", "REPLAY_START_DATE", "REPLAY_END_DATE", 
                "OUTCOME_WINDOW_BARS", "SCHEMA_NAME"):
        from .config import (
            REPLAY_SYMBOLS, REPLAY_START_DATE, REPLAY_END_DATE,
            OUTCOME_WINDOW_BARS, SCHEMA_NAME
        )
        return locals()[name]
    
    if name in ("run_replay", "ReplayStats"):
        from .runner import run_replay, ReplayStats
        return locals()[name]
    
    if name in ("CandleStore", "load_symbol_candles"):
        from .candle_store import CandleStore, load_symbol_candles
        return locals()[name]
    
    if name == "TimeframeAligner":
        from .timeframe_alignment import TimeframeAligner
        return TimeframeAligner
    
    if name in ("MarketStateManager", "SymbolState"):
        from .market_state import MarketStateManager, SymbolState
        return locals()[name]
    
    if name == "ReplaySignalDetector":
        from .signal_detector import ReplaySignalDetector
        return ReplaySignalDetector
    
    if name == "ReplayOutcomeCalculator":
        from .outcome_calculator import ReplayOutcomeCalculator
        return ReplayOutcomeCalculator
    
    raise AttributeError(f"module 'replay' has no attribute {name!r}")
