"""Replay runner - main orchestrator for the offline replay engine.

Single entrypoint to run full replay simulation. Coordinates:
1. Candle loading per symbol
2. Main replay loop (1H candle iteration)
3. State updates, signal detection, and outcome computation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from .config import (
    REPLAY_SYMBOLS,
    REPLAY_START_DATE,
    REPLAY_END_DATE,
    SCHEMA_NAME,
    OUTCOME_WINDOW_BARS,
    MAX_CHUNK_DAYS,
)
from .candle_store import load_symbol_candles
from .timeframe_alignment import TimeframeAligner
from .market_state import MarketStateManager
from .signal_detector import ReplaySignalDetector
from .outcome_calculator import ReplayOutcomeCalculator
from logger import get_logger

logger = get_logger(__name__)


def _generate_date_chunks(
    start_date: datetime, 
    end_date: datetime, 
    chunk_days: int = MAX_CHUNK_DAYS
) -> List[Tuple[datetime, datetime]]:
    """Split a date range into chunks to avoid TwelveData's 5000 candle limit.
    
    Args:
        start_date: Overall start date
        end_date: Overall end date
        chunk_days: Maximum days per chunk (default: MAX_CHUNK_DAYS)
        
    Returns:
        List of (chunk_start, chunk_end) tuples
    """
    chunks = []
    current_start = start_date
    
    while current_start < end_date:
        # Calculate chunk end (start + chunk_days or end_date)
        chunk_end = min(current_start + timedelta(days=chunk_days), end_date)
        chunks.append((current_start, chunk_end))
        current_start = chunk_end
    
    return chunks


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
    
    For long date ranges (>MAX_CHUNK_DAYS), the range is automatically split 
    into chunks to avoid TwelveData's 5000 candle limit.
    
    Args:
        symbols: List of forex symbols to replay (default: REPLAY_SYMBOLS)
        start_date: Replay start date (default: REPLAY_START_DATE)
        end_date: Replay end date (default: REPLAY_END_DATE)
        
    Returns:
        ReplayStats with summary of what was processed
    """
    symbols = symbols or REPLAY_SYMBOLS
    start_date = start_date or REPLAY_START_DATE
    end_date = end_date or REPLAY_END_DATE
    
    # Generate date chunks for long ranges
    chunks = _generate_date_chunks(start_date, end_date)
    
    stats = ReplayStats()
    
    logger.info("\n" + "=" * 60)
    logger.info("🔄 OFFLINE REPLAY ENGINE - Starting")
    logger.info("=" * 60)
    logger.info(f"  Symbols: {', '.join(symbols)}")
    logger.info(f"  Window: {start_date.isoformat()} to {end_date.isoformat()}")
    if len(chunks) > 1:
        logger.info(f"  Chunks: {len(chunks)} (max {MAX_CHUNK_DAYS} days each)")
    logger.info(f"  Schema: {SCHEMA_NAME}")
    logger.info("=" * 60 + "\n")
    
    # Process each symbol, chunk by chunk
    for symbol in symbols:
        for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks):
            if len(chunks) > 1:
                logger.info(
                    f"\n📦 Chunk {chunk_idx + 1}/{len(chunks)}: "
                    f"{chunk_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}"
                )
            
            symbol_stats = _replay_symbol(symbol, chunk_start, chunk_end)
            stats.candles_processed += symbol_stats.candles_processed
            stats.signals_inserted += symbol_stats.signals_inserted
            stats.outcomes_computed += symbol_stats.outcomes_computed
            stats.errors += symbol_stats.errors
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ REPLAY COMPLETE")
    logger.info(f"  {stats.summary()}")
    logger.info("=" * 60 + "\n")
        
    
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
    stats = ReplayStats()
    
    logger.info(f"\n--- 🔄 Processing {symbol} ---")
    
    # Step 1: Load candles
    logger.info(f"  📊 Loading candles for {symbol}...")
    try:
        candle_store = load_symbol_candles(symbol, start_date, end_date)
        candle_summary = candle_store.summary()
        logger.info(f"  ✅ Loaded: {candle_summary}")
    except Exception as e:
        import traceback
        logger.error(f"  ❌ Failed to load candles: {e}")
        traceback.print_exc()  # Print full traceback
        stats.errors += 1
        return stats
    
    # Step 2: Initialize components
    aligner = TimeframeAligner(candle_store)
    state_manager = MarketStateManager(symbol, candle_store, aligner)
    signal_detector = ReplaySignalDetector(symbol, candle_store)
    outcome_calculator = ReplayOutcomeCalculator(symbol, candle_store, start_date, end_date)
    
    # Step 3: Get 1H candle indices for replay window
    replay_indices = candle_store.get_replay_1h_indices(start_date, end_date)
    total_candles = len(replay_indices)
    
    logger.info(f"  📈 Replaying {total_candles} 1H candles...")
    
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
                logger.info(
                    f"    [{pct:5.1f}%] {stats.candles_processed} candles | "
                    f"{stats.signals_inserted} signals | "
                    f"{stats.outcomes_computed} outcomes"
                )
                
        except Exception as e:
            logger.error(f"    ❌ Error at candle {candle_idx}: {e}")
            stats.errors += 1
    
    # Step 5: Final pass - compute outcomes for ALL remaining pending signals
    # This catches signals near the end of the replay window that didn't have 
    # enough future candles during the main loop
    logger.info(f"  🔄 Final pass: computing remaining outcomes...")
    final_outcomes = _compute_remaining_outcomes(symbol, start_date, end_date, candle_store)
    stats.outcomes_computed += final_outcomes
    if final_outcomes > 0:
        logger.info(f"    ✅ Computed {final_outcomes} additional outcomes in final pass")
    
    logger.info(f"  ✅ {symbol} complete: {stats.summary()}")
    
    return stats


def _compute_remaining_outcomes(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    candle_store,
) -> int:
    """Compute outcomes for all remaining pending signals.
    
    This is called after the main replay loop to catch signals that
    didn't have enough future candles during the loop.
    """
    from database.executor import DBExecutor
    from psycopg2.extras import RealDictCursor
    from models import TrendDirection
    from signal_outcome.outcome_calculator import compute_outcome
    from signal_outcome.models import PendingSignal
    from .replay_queries import (
        FETCH_PENDING_REPLAY_SIGNALS,
        INSERT_REPLAY_SIGNAL_OUTCOME,
        INSERT_REPLAY_CHECKPOINT_RETURN,
        MARK_REPLAY_OUTCOME_COMPUTED,
    )
    from .config import BATCH_SIZE, OUTCOME_WINDOW_BARS
    
    computed_count = 0
    skipped_no_idx = 0
    skipped_no_candles = 0
    
    # Fetch ALL pending signals for this symbol (no time range filter)
    from .replay_queries import FETCH_ALL_PENDING_REPLAY_SIGNALS
    rows = DBExecutor.fetch_all(
        FETCH_ALL_PENDING_REPLAY_SIGNALS,
        params=(symbol, 1000),  # Just symbol and limit
        cursor_factory=RealDictCursor,
        context="fetch_final_pending_signals",
    )
    
    logger.info(f"    📋 Found {len(rows)} pending signals to process")
    
    for row in rows:
        signal_time = row["signal_time"]
        signal_idx = candle_store.get_1h_candles().find_index_by_time(signal_time)
        
        if signal_idx is None:
            skipped_no_idx += 1
            continue
        
        # Get future candles
        future_candles = candle_store.get_1h_candles().get_candles_after_index(
            signal_idx, OUTCOME_WINDOW_BARS
        )
        
        if future_candles is None or len(future_candles) < OUTCOME_WINDOW_BARS:
            skipped_no_candles += 1
            continue
        
        # Calculate sl_distance_atr
        direction = TrendDirection.from_raw(row["direction"])
        entry_price = float(row["entry_price"])
        atr_1h = float(row["atr_1h"])
        aoi_low = float(row["aoi_low"])
        aoi_high = float(row["aoi_high"])
        
        if direction == TrendDirection.BULLISH:
            far_edge_distance = entry_price - aoi_low
        else:
            far_edge_distance = aoi_high - entry_price
        
        sl_distance_atr = (far_edge_distance / atr_1h) + 0.25  # SL_BUFFER_ATR
        
        pending = PendingSignal(
            id=row["id"],
            symbol=row["symbol"],
            signal_time=signal_time,
            direction=row["direction"],
            entry_price=entry_price,
            atr_1h=atr_1h,
            aoi_low=aoi_low,
            aoi_high=aoi_high,
            sl_distance_atr=sl_distance_atr,
        )
        
        try:
            outcome = compute_outcome(pending, future_candles)
            
            # Persist outcome
            def _work(cursor):
                cursor.execute(
                    INSERT_REPLAY_SIGNAL_OUTCOME,
                    (
                        row["id"],
                        outcome.window_bars,
                        float(outcome.mfe_atr),
                        float(outcome.mae_atr),
                        outcome.bars_to_mfe,
                        outcome.bars_to_mae,
                        outcome.first_extreme,
                    ),
                )
                result = cursor.fetchone()
                cursor.execute(MARK_REPLAY_OUTCOME_COMPUTED, (row["id"],))
                return result is not None
            
            if DBExecutor.execute_transaction(_work, context="persist_final_outcome"):
                computed_count += 1
                
        except Exception:
            pass  # Skip signals with errors
    
    # Summary: show why signals were skipped
    if skipped_no_idx > 0 or skipped_no_candles > 0:
        logger.info(
            f"    ⚠️ Skipped: {skipped_no_idx} (no index found), {skipped_no_candles} (not enough future candles)"
        )
    
    return computed_count


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
