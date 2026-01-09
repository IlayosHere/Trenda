"""Repository for signal outcome database operations."""

from typing import Optional

from psycopg2.extras import RealDictCursor

from database.executor import DBExecutor
from database.queries import (
    FETCH_PENDING_SIGNALS,
    INSERT_SIGNAL_OUTCOME,
    MARK_OUTCOME_COMPUTED,
)

from .models import OutcomeData, PendingSignal


def _safe_float(value: float | None) -> float | None:
    """Convert to float if not None, otherwise return None."""
    return float(value) if value is not None else None


def fetch_pending_signals(batch_size: int) -> list[PendingSignal]:
    """
    Fetch signals where outcome_computed = FALSE and entry_price IS NOT NULL.
    
    Args:
        batch_size: Maximum number of signals to fetch
        
    Returns:
        List of PendingSignal objects ordered by signal_time ASC
    """
    rows = DBExecutor.fetch_all(
        FETCH_PENDING_SIGNALS,
        params=(batch_size,),
        cursor_factory=RealDictCursor,
        context="fetch_pending_signals",
    )
    
    return [
        PendingSignal(
            id=row["id"],
            symbol=row["symbol"],
            signal_time=row["signal_time"],
            direction=row["direction"],
            entry_price=row["entry_price"],
            atr_1h=row["atr_1h"],
            aoi_low=row["aoi_low"],
            aoi_high=row["aoi_high"],
            sl_distance_atr=row["sl_distance_atr"],
        )
        for row in rows
    ]


def persist_outcome(entry_signal_id: int, outcome: OutcomeData) -> bool:
    """
    Persist outcome and mark signal as computed in a transaction.
    
    This ensures both operations succeed or neither does.
    
    Args:
        entry_signal_id: ID of the entry signal
        outcome: Computed outcome data
        
    Returns:
        True if both operations succeeded
    """
    def _work(cursor):
        # Insert outcome (idempotent - ON CONFLICT DO NOTHING)
        cursor.execute(
            INSERT_SIGNAL_OUTCOME,
            (
                entry_signal_id,
                outcome.window_bars,
                float(outcome.mfe_atr),
                float(outcome.mae_atr),
                outcome.bars_to_mfe,
                outcome.bars_to_mae,
                outcome.first_extreme,
                _safe_float(outcome.return_after_48),
                _safe_float(outcome.return_after_72),
                _safe_float(outcome.return_after_96),
                outcome.exit_reason,
                outcome.bars_to_exit,
            ),
        )
        
        # Mark as computed
        cursor.execute(MARK_OUTCOME_COMPUTED, (entry_signal_id,))
        return True
    
    result = DBExecutor.execute_transaction(_work, context="persist_outcome")
    return result if result is not None else False


def mark_outcome_computed(entry_signal_id: int) -> bool:
    """
    Mark a signal as having its outcome computed.
    
    Args:
        entry_signal_id: ID of the entry signal
        
    Returns:
        True if update succeeded
    """
    return DBExecutor.execute_non_query(
        MARK_OUTCOME_COMPUTED,
        params=(entry_signal_id,),
        context="mark_outcome_computed",
    )
