"""Outcome computation for replay.

Computes signal outcomes deterministically during the replay loop,
using in-memory candle data instead of API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

import pandas as pd

from models import TrendDirection
from signal_outcome.outcome_calculator import compute_outcome
from signal_outcome.models import OutcomeWithCheckpoints, PendingSignal

from .candle_store import CandleStore
from .config import OUTCOME_WINDOW_BARS, BATCH_SIZE
from .replay_queries import (
    FETCH_PENDING_REPLAY_SIGNALS,
    INSERT_REPLAY_SIGNAL_OUTCOME,
    INSERT_REPLAY_CHECKPOINT_RETURN,
    MARK_REPLAY_OUTCOME_COMPUTED,
)
from .path_extremes import PathExtremesCalculator, persist_path_extremes
from .sl_geometry import SLGeometryCalculator, persist_sl_geometry
from .exit_simulator import ExitSimulator, persist_exit_simulations


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
    signal_1h_index: Optional[int] = None


@dataclass
class ReplayOutcomeResult:
    """Computed outcome result for replay."""
    
    # Core outcome
    window_bars: int
    mfe_atr: float
    mae_atr: float
    bars_to_mfe: int
    bars_to_mae: int
    first_extreme: str
    
    # Checkpoint returns
    checkpoint_returns: list


class ReplayOutcomeCalculator:
    """Computes outcomes for signals during replay.
    
    Unlike the production outcome processor which fetches candles via API,
    this uses the in-memory candle store, ensuring no API calls during
    the replay loop.
    """
    
    def __init__(self, symbol: str, candle_store: CandleStore, start_date: datetime = None, end_date: datetime = None):
        self._symbol = symbol
        self._store = candle_store
        self._start_date = start_date
        self._end_date = end_date
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
        
        # Fetch pending signals from replay DB (filtered by symbol and time range)
        pending_signals = self._fetch_pending_signals()
        
        for signal in pending_signals:
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
            
            # Check if eligible (72 candles have passed)
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
        from database.executor import DBExecutor
        
        rows = DBExecutor.fetch_all(
            FETCH_PENDING_REPLAY_SIGNALS,
            params=(self._symbol, self._start_date, self._end_date, BATCH_SIZE),
            cursor_factory=RealDictCursor,
            context="fetch_pending_replay_signals",
        )
        
        signals = []
        for row in rows:
            signals.append(ReplayPendingSignal(
                id=row["id"],
                symbol=row["symbol"],
                signal_time=row["signal_time"],
                direction=row["direction"],
                entry_price=float(row["entry_price"]),
                atr_1h=float(row["atr_1h"]),
                aoi_low=float(row["aoi_low"]),
                aoi_high=float(row["aoi_high"]),
            ))
        return signals
    
    def _compute_and_persist_outcome(
        self,
        signal: ReplayPendingSignal,
        candles: pd.DataFrame,
    ) -> bool:
        """Compute outcome and persist to replay schema."""
        direction = TrendDirection.from_raw(signal.direction)
        
        # Use production logic for base outcome (MFE/MAE in ATR units)
        pending = PendingSignal(
            id=signal.id,
            symbol=signal.symbol,
            signal_time=signal.signal_time,
            direction=signal.direction,
            entry_price=signal.entry_price,
            atr_1h=signal.atr_1h,
            aoi_low=signal.aoi_low,
            aoi_high=signal.aoi_high,
            aoi_effective_sl_distance_price=signal.atr_1h,  # Placeholder, not used
        )
        
        base_result = compute_outcome(pending, candles)
        outcome = base_result.outcome
        
        # Build simplified result
        replay_result = ReplayOutcomeResult(
            window_bars=outcome.window_bars,
            mfe_atr=outcome.mfe_atr,
            mae_atr=outcome.mae_atr,
            bars_to_mfe=outcome.bars_to_mfe,
            bars_to_mae=outcome.bars_to_mae,
            first_extreme=outcome.first_extreme,
            checkpoint_returns=base_result.checkpoint_returns,
        )
        
        # Persist main outcome atomically
        success = self._persist_outcome(signal.id, replay_result)
        
        if success:
            # Compute and persist exit simulation data
            self._compute_exit_simulation_data(
                signal_id=signal.id,
                signal=signal,
                candles=candles,
                direction=direction,
            )
        
        return success
    
    def _compute_exit_simulation_data(
        self,
        signal_id: int,
        signal: ReplayPendingSignal,
        candles: pd.DataFrame,
        direction: TrendDirection,
    ) -> None:
        """Compute and persist exit simulation data (path, geometry, simulations)."""
        # Get signal candle index
        signal_idx = self._signal_indices.get(signal_id)
        if signal_idx is None:
            return
        
        # Get the signal candle (last candle at signal time)
        signal_candle_data = self._store.get_1h_candles().get_candle_at_index(signal_idx)
        if signal_candle_data is None:
            return
        
        signal_candle = {
            "open": float(signal_candle_data["open"]),
            "high": float(signal_candle_data["high"]),
            "low": float(signal_candle_data["low"]),
            "close": float(signal_candle_data["close"]),
        }
        
        # 1. Compute path extremes (bars 1-72)
        path_calc = PathExtremesCalculator(
            candle_store=self._store,
            entry_candle_idx=signal_idx,
            entry_price=signal.entry_price,
            atr_at_entry=signal.atr_1h,
            direction=direction,
        )
        path_rows = path_calc.compute()
        if path_rows:
            persist_path_extremes(signal_id, path_rows)
        
        # 2. Compute SL geometry
        geometry_calc = SLGeometryCalculator(
            entry_price=signal.entry_price,
            atr_at_entry=signal.atr_1h,
            direction=direction,
            aoi_low=signal.aoi_low,
            aoi_high=signal.aoi_high,
            signal_candle=signal_candle,
            signal_time=signal.signal_time,
        )
        geometry = geometry_calc.compute()
        if geometry:
            persist_sl_geometry(signal_id, geometry)
            
            # 3. Run exit simulator (requires both path and geometry)
            if path_rows:
                simulator = ExitSimulator(geometry=geometry, path_extremes=path_rows)
                sim_rows = simulator.simulate_all()
                if sim_rows:
                    persist_exit_simulations(signal_id, sim_rows)
    
    def _persist_outcome(self, signal_id: int, result: ReplayOutcomeResult) -> bool:
        """Persist outcome and mark signal as computed in a transaction."""
        from database.executor import DBExecutor
        
        def _work(cursor):
            # Insert outcome with simplified schema
            cursor.execute(
                INSERT_REPLAY_SIGNAL_OUTCOME,
                (
                    signal_id,
                    result.window_bars,
                    float(result.mfe_atr),
                    float(result.mae_atr),
                    result.bars_to_mfe,
                    result.bars_to_mae,
                    result.first_extreme,
                ),
            )
            row = cursor.fetchone()
            if not row:
                return False
            outcome_id = row[0]
            
            # Insert checkpoint returns
            for cp in result.checkpoint_returns:
                cursor.execute(
                    INSERT_REPLAY_CHECKPOINT_RETURN,
                    (outcome_id, cp.bars_after, float(cp.return_atr)),
                )
            
            # Mark as computed
            cursor.execute(MARK_REPLAY_OUTCOME_COMPUTED, (signal_id,))
            return True
        
        result = DBExecutor.execute_transaction(_work, context="persist_replay_outcome")
        return result if result is not None else False
