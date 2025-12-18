"""Outcome computation for replay.

Computes signal outcomes deterministically during the replay loop,
using in-memory candle data instead of API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

import pandas as pd

from models import TrendDirection
from signal_outcome.outcome_calculator import compute_outcome
from signal_outcome.models import OutcomeData, PendingSignal
from database.executor import DBExecutor

from .candle_store import CandleStore
from .config import OUTCOME_WINDOW_BARS, BATCH_SIZE
from .replay_queries import (
    FETCH_PENDING_REPLAY_SIGNALS,
    INSERT_REPLAY_SIGNAL_OUTCOME,
    MARK_REPLAY_OUTCOME_COMPUTED,
)


@dataclass
class ReplayPendingSignal:
    """Signal awaiting outcome computation in replay."""
    
    id: int
    symbol: str
    signal_time: datetime
    direction: str
    entry_price: float
    atr_1h: float
    aoi_low: float
    aoi_high: float
    aoi_effective_sl_distance_price: float
    signal_1h_index: Optional[int] = None


class ReplayOutcomeCalculator:
    """Computes outcomes for signals during replay.
    
    Unlike the production outcome processor which fetches candles via API,
    this uses the in-memory candle store, ensuring no API calls during
    the replay loop.
    """
    
    def __init__(self, symbol: str, candle_store: CandleStore):
        self._symbol = symbol
        self._store = candle_store
        self._signal_indices: dict[int, int] = {}  # signal_id -> 1H candle index
    
    def register_signal(self, signal_id: int, signal_time: datetime) -> None:
        """Register a signal with its 1H candle index for later outcome computation.
        
        Called when a signal is inserted so we can track its position in the candle store.
        """
        idx = self._store.get_1h_candles().find_index_by_time(signal_time)
        if idx is not None:
            self._signal_indices[signal_id] = idx
    
    def compute_eligible_outcomes(self, current_1h_index: int) -> int:
        """Compute outcomes for signals that are now eligible.
        
        A signal is eligible when 48 candles have passed since its signal time.
        
        Args:
            current_1h_index: Current index in the 1H candle iteration
            
        Returns:
            Number of outcomes computed
        """
        computed_count = 0
        
        # Fetch pending signals from replay DB
        pending_signals = self._fetch_pending_signals()
        
        for signal in pending_signals:
            # Skip if not for this symbol
            if signal.symbol != self._symbol:
                continue
            
            # Get signal's 1H index
            signal_idx = self._signal_indices.get(signal.id)
            if signal_idx is None:
                # Try to find it
                signal_idx = self._store.get_1h_candles().find_index_by_time(
                    signal.signal_time
                )
                if signal_idx is not None:
                    self._signal_indices[signal.id] = signal_idx
            
            if signal_idx is None:
                continue
            
            # Check if eligible (48 candles have passed)
            if current_1h_index < signal_idx + OUTCOME_WINDOW_BARS:
                continue
            
            # Get future candles from store
            future_candles = self._store.get_1h_candles().get_candles_after_index(
                signal_idx, OUTCOME_WINDOW_BARS
            )
            
            if len(future_candles) < OUTCOME_WINDOW_BARS:
                continue
            
            # Compute and persist outcome
            if self._compute_and_persist_outcome(signal, future_candles):
                computed_count += 1
                # Remove from tracking
                self._signal_indices.pop(signal.id, None)
        
        return computed_count
    
    def _fetch_pending_signals(self) -> List[ReplayPendingSignal]:
        """Fetch signals where outcome_computed = FALSE from replay schema."""
        from psycopg2.extras import RealDictCursor
        
        rows = DBExecutor.fetch_all(
            FETCH_PENDING_REPLAY_SIGNALS,
            params=(BATCH_SIZE,),
            cursor_factory=RealDictCursor,
            context="fetch_pending_replay_signals",
        )
        
        return [
            ReplayPendingSignal(
                id=row["id"],
                symbol=row["symbol"],
                signal_time=row["signal_time"],
                direction=row["direction"],
                entry_price=float(row["entry_price"]),
                atr_1h=float(row["atr_1h"]),
                aoi_low=float(row["aoi_low"]),
                aoi_high=float(row["aoi_high"]),
                aoi_effective_sl_distance_price=float(row["aoi_effective_sl_distance_price"]),
            )
            for row in rows
        ]
    
    def _compute_and_persist_outcome(
        self,
        signal: ReplayPendingSignal,
        candles: pd.DataFrame,
    ) -> bool:
        """Compute outcome and persist to replay schema."""
        # Convert to PendingSignal for compatibility with production calculator
        pending = PendingSignal(
            id=signal.id,
            symbol=signal.symbol,
            signal_time=signal.signal_time,
            direction=signal.direction,
            entry_price=signal.entry_price,
            atr_1h=signal.atr_1h,
            aoi_low=signal.aoi_low,
            aoi_high=signal.aoi_high,
            aoi_effective_sl_distance_price=signal.aoi_effective_sl_distance_price,
        )
        
        # Compute outcome using production logic
        outcome = compute_outcome(pending, candles)
        
        # Persist atomically
        return self._persist_outcome(signal.id, outcome)
    
    def _persist_outcome(self, signal_id: int, outcome: OutcomeData) -> bool:
        """Persist outcome and mark signal as computed in a transaction."""
        def _safe_float(value):
            return float(value) if value is not None else None
        
        def _work(cursor):
            # Insert outcome
            cursor.execute(
                INSERT_REPLAY_SIGNAL_OUTCOME,
                (
                    signal_id,
                    outcome.window_bars,
                    float(outcome.mfe_atr),
                    float(outcome.mae_atr),
                    outcome.bars_to_mfe,
                    outcome.bars_to_mae,
                    outcome.first_extreme,
                    _safe_float(outcome.return_after_3),
                    _safe_float(outcome.return_after_6),
                    _safe_float(outcome.return_after_12),
                    _safe_float(outcome.return_after_24),
                    _safe_float(outcome.return_end_window),
                    outcome.bars_to_aoi_sl_hit,
                    outcome.bars_to_r_1,
                    outcome.bars_to_r_1_5,
                    outcome.bars_to_r_2,
                    outcome.aoi_rr_outcome,
                ),
            )
            
            # Mark as computed
            cursor.execute(MARK_REPLAY_OUTCOME_COMPUTED, (signal_id,))
            return True
        
        result = DBExecutor.execute_transaction(_work, context="persist_replay_outcome")
        return result if result is not None else False
