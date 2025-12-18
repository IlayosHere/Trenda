"""Replay runner - main orchestrator for the offline replay engine.

Single entrypoint to run full replay simulation. Coordinates:
1. Candle loading per symbol
2. Main replay loop (1H candle iteration)
3. State updates, signal detection, and outcome computation
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from .config import (
    REPLAY_SYMBOLS,
    REPLAY_START_DATE,
    REPLAY_END_DATE,
    SCHEMA_NAME,
    OUTCOME_WINDOW_BARS,
)
from .candle_store import load_symbol_candles
from .timeframe_alignment import TimeframeAligner
from .market_state import MarketStateManager
from .signal_detector import ReplaySignalDetector
from .outcome_calculator import ReplayOutcomeCalculator


class ReplayStats:
    """Statistics for a replay run."""
    
    def __init__(self):
        self.candles_processed = 0
        self.signals_inserted = 0
        self.outcomes_computed = 0
        self.errors = 0
    
    def summary(self) -> str:
        return (
            f"Candles: {self.candles_processed} | "
            f"Signals: {self.signals_inserted} | "
            f"Outcomes: {self.outcomes_computed} | "
            f"Errors: {self.errors}"
        )


def run_replay(
    symbols: Optional[List[str]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ReplayStats:
    """Run the offline replay simulation.
    
    Args:
        symbols: List of forex symbols to replay (default: REPLAY_SYMBOLS)
        start_date: Replay start date (default: REPLAY_START_DATE)
        end_date: Replay end date (default: REPLAY_END_DATE)
        
    Returns:
        ReplayStats with summary of what was processed
    """
    # Deferred imports to avoid circular import issues
    import utils.display as display
    
    symbols = symbols or REPLAY_SYMBOLS
    start_date = start_date or REPLAY_START_DATE
    end_date = end_date or REPLAY_END_DATE
    
    stats = ReplayStats()
    
    display.print_status("\n" + "=" * 60)
    display.print_status("🔄 OFFLINE REPLAY ENGINE - Starting")
    display.print_status("=" * 60)
    display.print_status(f"  Symbols: {', '.join(symbols)}")
    display.print_status(f"  Window: {start_date.isoformat()} to {end_date.isoformat()}")
    display.print_status(f"  Schema: {SCHEMA_NAME}")
    display.print_status("=" * 60 + "\n")
    
    # Process each symbol
    for symbol in symbols:
        symbol_stats = _replay_symbol(symbol, start_date, end_date)
        stats.candles_processed += symbol_stats.candles_processed
        stats.signals_inserted += symbol_stats.signals_inserted
        stats.outcomes_computed += symbol_stats.outcomes_computed
        stats.errors += symbol_stats.errors
    
    display.print_status("\n" + "=" * 60)
    display.print_status("✅ REPLAY COMPLETE")
    display.print_status(f"  {stats.summary()}")
    display.print_status("=" * 60 + "\n")
        
    
    return stats


def _replay_symbol(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
) -> ReplayStats:
    """Run replay for a single symbol.
    
    Args:
        symbol: Forex pair symbol
        start_date: Replay start date
        end_date: Replay end date
        
    Returns:
        ReplayStats for this symbol
    """
    import utils.display as display
    
    stats = ReplayStats()
    
    display.print_status(f"\n--- 🔄 Processing {symbol} ---")
    
    # Step 1: Load candles
    display.print_status(f"  📊 Loading candles for {symbol}...")
    try:
        candle_store = load_symbol_candles(symbol, start_date, end_date)
        candle_summary = candle_store.summary()
        display.print_status(f"  ✅ Loaded: {candle_summary}")
    except Exception as e:
        display.print_error(f"  ❌ Failed to load candles: {e}")
        stats.errors += 1
        return stats
    
    # Step 2: Initialize components
    aligner = TimeframeAligner(candle_store)
    state_manager = MarketStateManager(symbol, candle_store, aligner)
    signal_detector = ReplaySignalDetector(symbol, candle_store)
    outcome_calculator = ReplayOutcomeCalculator(symbol, candle_store)
    
    # Step 3: Get 1H candle indices for replay window
    replay_indices = candle_store.get_replay_1h_indices(start_date, end_date)
    total_candles = len(replay_indices)
    
    display.print_status(f"  📈 Replaying {total_candles} 1H candles...")
    
    # Progress tracking
    log_interval = max(total_candles // 10, 1)  # Log every 10%
    
    # Step 4: Main replay loop
    for i, candle_idx in enumerate(replay_indices):
        try:
            candle = candle_store.get_1h_candles().get_candle_at_index(candle_idx)
            if candle is None:
                continue
            
            current_time = candle["time"]
            
            # Update market state (only recomputes if new TF close)
            state_manager.update_state(current_time)
            
            # Detect entry signals
            signal_ids = signal_detector.detect_signals(
                current_time, state_manager.state
            )
            stats.signals_inserted += len(signal_ids)
            
            # Register signals for outcome tracking
            for sig_id in signal_ids:
                outcome_calculator.register_signal(sig_id, current_time)
            
            # Compute outcomes for eligible signals
            outcomes = outcome_calculator.compute_eligible_outcomes(candle_idx)
            stats.outcomes_computed += outcomes
            
            stats.candles_processed += 1
            
            # Progress logging
            if (i + 1) % log_interval == 0 or i == total_candles - 1:
                pct = ((i + 1) / total_candles) * 100
                display.print_status(
                    f"    [{pct:5.1f}%] {stats.candles_processed} candles | "
                    f"{stats.signals_inserted} signals | "
                    f"{stats.outcomes_computed} outcomes"
                )
                
        except Exception as e:
            display.print_error(f"    ❌ Error at candle {candle_idx}: {e}")
            stats.errors += 1
    
    display.print_status(f"  ✅ {symbol} complete: {stats.summary()}")
    
    return stats


def main():
    """CLI entrypoint for running replay."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run offline replay engine for trading signal simulation"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help=f"Symbols to replay (default: {REPLAY_SYMBOLS})",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help=f"Start date ISO format (default: {REPLAY_START_DATE.isoformat()})",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help=f"End date ISO format (default: {REPLAY_END_DATE.isoformat()})",
    )
    
    args = parser.parse_args()
    
    # Parse dates if provided
    start_date = None
    end_date = None
    if args.start:
        start_date = datetime.fromisoformat(args.start)
    if args.end:
        end_date = datetime.fromisoformat(args.end)
    
    # Run replay
    stats = run_replay(
        symbols=args.symbols,
        start_date=start_date,
        end_date=end_date,
    )
    
    # Exit with error code if any errors occurred
    exit(1 if stats.errors > 0 else 0)


if __name__ == "__main__":
    main()
