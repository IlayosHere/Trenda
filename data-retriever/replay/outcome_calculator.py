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
    TP_R_MULTIPLIER,
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
    effective_sl_distance_price: float  # Renamed from aoi_effective_sl_distance_price
    effective_tp_distance_price: float  # New field
    signal_1h_index: Optional[int] = None


@dataclass
class ReplayOutcomeResult:
    """Computed outcome result for replay with new fields."""
    
    # Core outcome from production calculator
    window_bars: int
    mfe_atr: float
    mae_atr: float
    bars_to_mfe: int
    bars_to_mae: int
    first_extreme: str
    
    # New outcome fields
    realized_r: Optional[float]
    exit_reason: Optional[str]  # 'TP', 'SL', 'TIME'
    bars_to_exit: Optional[int]
    mfe_r: float  # MFE in R units (normalized by effective SL)
    mae_r: float  # MAE in R units (normalized by effective SL)
    bars_to_tp: Optional[int]
    bars_to_sl: Optional[int]
    
    # Checkpoint returns
    checkpoint_returns: list


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
            
            # Check if eligible (168 candles have passed)
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
            params=(BATCH_SIZE,),
            cursor_factory=RealDictCursor,
            context="fetch_pending_replay_signals",
        )
        
        signals = []
        for row in rows:
            sl_dist = float(row["effective_sl_distance_price"])
            # TP distance is always computed from SL using 2.25R multiplier
            tp_dist = sl_dist * TP_R_MULTIPLIER
            
            signals.append(ReplayPendingSignal(
                id=row["id"],
                symbol=row["symbol"],
                signal_time=row["signal_time"],
                direction=row["direction"],
                entry_price=float(row["entry_price"]),
                atr_1h=float(row["atr_1h"]),
                aoi_low=float(row["aoi_low"]),
                aoi_high=float(row["aoi_high"]),
                effective_sl_distance_price=sl_dist,
                effective_tp_distance_price=tp_dist,
            ))
        return signals
    
    def _compute_and_persist_outcome(
        self,
        signal: ReplayPendingSignal,
        candles: pd.DataFrame,
    ) -> bool:
        """Compute outcome and persist to replay schema."""
        direction = TrendDirection.from_raw(signal.direction)
        is_bullish = direction == TrendDirection.BULLISH
        
        # Use production logic for base outcome
        pending = PendingSignal(
            id=signal.id,
            symbol=signal.symbol,
            signal_time=signal.signal_time,
            direction=signal.direction,
            entry_price=signal.entry_price,
            atr_1h=signal.atr_1h,
            aoi_low=signal.aoi_low,
            aoi_high=signal.aoi_high,
            aoi_effective_sl_distance_price=signal.effective_sl_distance_price,
        )
        
        base_result = compute_outcome(pending, candles)
        outcome = base_result.outcome
        
        # Compute new outcome fields
        replay_result = self._compute_new_outcome_fields(
            signal=signal,
            candles=candles,
            base_outcome=outcome,
            checkpoint_returns=base_result.checkpoint_returns,
            is_bullish=is_bullish,
        )
        
        # Persist atomically
        return self._persist_outcome(signal.id, replay_result)
    
    def _compute_new_outcome_fields(
        self,
        signal: ReplayPendingSignal,
        candles: pd.DataFrame,
        base_outcome,
        checkpoint_returns: list,
        is_bullish: bool,
    ) -> ReplayOutcomeResult:
        """Compute the new outcome fields (realized_r, exit_reason, etc.)."""
        entry_price = signal.entry_price
        sl_distance = signal.effective_sl_distance_price
        tp_distance = signal.effective_tp_distance_price
        
        # Compute SL and TP price levels
        if is_bullish:
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance
        
        # Detect SL/TP hits with single TP
        bars_to_sl = None
        bars_to_tp = None
        mfe_price = 0.0
        mae_price = 0.0
        
        for bar_num, (_, candle) in enumerate(candles.iterrows(), start=1):
            high = candle["high"]
            low = candle["low"]
            
            # Track MFE/MAE in price terms
            if is_bullish:
                favorable = high - entry_price
                adverse = entry_price - low
            else:
                favorable = entry_price - low
                adverse = high - entry_price
            
            mfe_price = max(mfe_price, favorable)
            mae_price = max(mae_price, adverse)
            
            # Check SL hit
            if bars_to_sl is None:
                if is_bullish and low <= sl_price:
                    bars_to_sl = bar_num
                elif not is_bullish and high >= sl_price:
                    bars_to_sl = bar_num
            
            # Check TP hit
            if bars_to_tp is None:
                if is_bullish and high >= tp_price:
                    bars_to_tp = bar_num
                elif not is_bullish and low <= tp_price:
                    bars_to_tp = bar_num
        
        # Compute MFE/MAE in R units (normalized by SL distance)
        mfe_r = mfe_price / sl_distance if sl_distance > 0 else 0.0
        mae_r = mae_price / sl_distance if sl_distance > 0 else 0.0
        
        # Determine exit reason and bars to exit
        exit_reason, bars_to_exit, realized_r = self._determine_exit(
            bars_to_sl=bars_to_sl,
            bars_to_tp=bars_to_tp,
            window_bars=OUTCOME_WINDOW_BARS,
            tp_r_multiplier=TP_R_MULTIPLIER,
        )
        
        return ReplayOutcomeResult(
            window_bars=base_outcome.window_bars,
            mfe_atr=base_outcome.mfe_atr,
            mae_atr=base_outcome.mae_atr,
            bars_to_mfe=base_outcome.bars_to_mfe,
            bars_to_mae=base_outcome.bars_to_mae,
            first_extreme=base_outcome.first_extreme,
            realized_r=realized_r,
            exit_reason=exit_reason,
            bars_to_exit=bars_to_exit,
            mfe_r=mfe_r,
            mae_r=mae_r,
            bars_to_tp=bars_to_tp,
            bars_to_sl=bars_to_sl,
            checkpoint_returns=checkpoint_returns,
        )
    
    def _determine_exit(
        self,
        bars_to_sl: Optional[int],
        bars_to_tp: Optional[int],
        window_bars: int,
        tp_r_multiplier: float,
    ) -> tuple[Optional[str], Optional[int], Optional[float]]:
        """Determine the exit reason, bars to exit, and realized R."""
        # Neither SL nor TP hit
        if bars_to_sl is None and bars_to_tp is None:
            return 'TIME', window_bars, None
        
        # Only SL hit
        if bars_to_sl is not None and bars_to_tp is None:
            return 'SL', bars_to_sl, -1.0
        
        # Only TP hit
        if bars_to_tp is not None and bars_to_sl is None:
            return 'TP', bars_to_tp, tp_r_multiplier
        
        # Both hit - determine which came first
        if bars_to_tp <= bars_to_sl:
            return 'TP', bars_to_tp, tp_r_multiplier
        else:
            return 'SL', bars_to_sl, -1.0
    
    def _persist_outcome(self, signal_id: int, result: ReplayOutcomeResult) -> bool:
        """Persist outcome and mark signal as computed in a transaction."""
        from database.executor import DBExecutor
        
        def _work(cursor):
            # Insert outcome with new schema (no legacy columns)
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
                    # New fields
                    result.realized_r,
                    result.exit_reason,
                    result.bars_to_exit,
                    float(result.mfe_r),
                    float(result.mae_r),
                    result.bars_to_tp,
                    result.bars_to_sl,
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
