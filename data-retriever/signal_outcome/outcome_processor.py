"""Main processor for computing signal outcomes."""

from datetime import datetime, timezone

from logger import get_logger

logger = get_logger(__name__)

from .candle_counter import count_closed_1h_candles_between
from .candle_fetcher import fetch_candles_after_signal
from .constants import BATCH_SIZE, OUTCOME_WINDOW_BARS, ProcessResult
from .models import PendingSignal
from .outcome_calculator import compute_outcome
from .repository import fetch_pending_signals, persist_outcome


def run_signal_outcome_processor() -> None:
    """
    Process pending signals and compute their outcomes.
    
    This processor runs every 1H with a 2 min offset.
    It is fully idempotent - safe to run multiple times.
    """
    logger.info("\n--- 🔄 Running signal outcome processor ---")
    
    # STEP 1: Fetch candidate signals
    signals = fetch_pending_signals(BATCH_SIZE)
    
    if not signals:
        logger.info("  ℹ️  No pending signals to process.")
        logger.info("--- ✅ Signal outcome processor complete ---\n")
        return
    
    logger.info(f"  📊 Found {len(signals)} pending signal(s).")
    
    now_utc = datetime.now(timezone.utc)
    stats = _process_signal_batch(signals, now_utc)
    
    logger.info(
        f"  📈 Processed: {stats[ProcessResult.PROCESSED]} | "
        f"Not ready: {stats[ProcessResult.NOT_READY]} | "
        f"Missing candles: {stats[ProcessResult.MISSING_CANDLES]}"
    )
    logger.info("--- ✅ Signal outcome processor complete ---\n")


def _process_signal_batch(
    signals: list[PendingSignal], now_utc: datetime
) -> dict[ProcessResult, int]:
    """Process a batch of signals and return statistics."""
    stats = {result: 0 for result in ProcessResult}
    
    for signal in signals:
        result = _process_single_signal(signal, now_utc)
        stats[result] += 1
    
    return stats


def _process_single_signal(signal: PendingSignal, now_utc: datetime) -> ProcessResult:
    """
    Process a single signal through Steps 2-4.
    
    Returns:
        ProcessResult enum value indicating the outcome
    """
    # STEP 2: Check readiness
    if not _is_signal_ready(signal.signal_time, now_utc):
        return ProcessResult.NOT_READY
    
    # STEP 3: Fetch future candles
    candles = fetch_candles_after_signal(signal.symbol, signal.signal_time)
    
    if candles is None or len(candles) < OUTCOME_WINDOW_BARS:
        return ProcessResult.MISSING_CANDLES
    
    # STEP 4: Compute outcome
    outcome = compute_outcome(signal, candles)
    
    # Persist outcome and mark as computed
    success = persist_outcome(signal.id, outcome)
    
    if success:
        logger.info(
            f"  ✅ Computed outcome for signal {signal.id} ({signal.symbol})"
        )
        return ProcessResult.PROCESSED
    else:
        logger.error(
            f"  ❌ Failed to persist outcome for signal {signal.id}"
        )
        return ProcessResult.ERROR


def _is_signal_ready(signal_time: datetime, now_utc: datetime) -> bool:
    """Check if enough time has passed for outcome computation."""
    expected_candles = count_closed_1h_candles_between(signal_time, now_utc)
    return expected_candles >= OUTCOME_WINDOW_BARS
