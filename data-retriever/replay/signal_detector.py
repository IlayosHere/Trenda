"""Entry signal detection for replay.

Reuses production logic to detect entry patterns and evaluate quality,
then persists to the replay schema with idempotency checks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

import pandas as pd

from models import AOIZone, TrendDirection
from models.market import Candle, SignalData
from entry.pattern_finder import find_entry_pattern
from entry.quality import evaluate_entry_quality
from entry.sl_calculator import compute_sl_tp_distances
from utils.indicators import calculate_atr

from .market_state import SymbolState
from .candle_store import CandleStore
from .config import LOOKBACK_1H, TIMEFRAME_1H
from .replay_queries import (
    CHECK_SIGNAL_EXISTS,
    GET_SIGNAL_ID,
    INSERT_REPLAY_ENTRY_SIGNAL,
    INSERT_REPLAY_ENTRY_SIGNAL_SCORE,
    INSERT_REPLAY_PRE_ENTRY_CONTEXT,
)
from .pre_entry_context import PreEntryContextCalculator, PreEntryContextData

SL_MODEL_VERSION = 'AOI_MAX_ATR_2_5_v1'
TP_MODEL_VERSION = 'TP_SINGLE_2_25R_v1'

class ReplaySignalDetector:
    """Detects entry signals during replay using production logic.
    
    For each 1H candle close:
    1. Gets current 1H candles (up to lookback)
    2. Gets tradable AOIs from current market state
    3. Finds entry patterns for each AOI
    4. Evaluates quality and computes SL/TP distances
    5. Persists to replay schema (if not duplicate)
    """
    
    def __init__(self, symbol: str, candle_store: CandleStore):
        self._symbol = symbol
        self._store = candle_store
    
    def detect_signals(
        self,
        current_time: datetime,
        state: SymbolState,
    ) -> List[int]:
        """Detect and store entry signals at current time.
        
        Args:
            current_time: Current simulation time (1H candle close)
            state: Current market state (trends + AOIs)
            
        Returns:
            List of signal IDs that were inserted
        """
        inserted_ids = []
        
        # Get overall trend direction
        direction = state.get_overall_trend()
        if direction is None:
            return inserted_ids
        
        # Get 1H candles for pattern detection
        candles_1h = self._store.get_1h_candles().get_candles_up_to(current_time)
        if candles_1h is None or candles_1h.empty:
            return inserted_ids
        
        # Limit to lookback
        candles_1h = candles_1h.tail(LOOKBACK_1H)
        
        # Calculate 1H ATR
        atr_1h = calculate_atr(candles_1h)
        if atr_1h <= 0:
            return inserted_ids
        
        # Build trend snapshot
        trend_snapshot = {
            "4H": state.trend_4h,
            "1D": state.trend_1d,
            "1W": state.trend_1w,
        }
        
        # Get trend alignment strength
        trend_alignment = state.get_trend_alignment_strength(direction)
        
        # Get tradable AOIs
        tradable_aois = state.get_tradable_aois()
        
        # Scan each AOI for entry pattern
        for aoi in tradable_aois:
            signal_id = self._scan_aoi_for_entry(
                candles_1h=candles_1h,
                aoi=aoi,
                direction=direction,
                trend_snapshot=trend_snapshot,
                trend_alignment=trend_alignment,
                atr_1h=atr_1h,
            )
            if signal_id:
                inserted_ids.append(signal_id)
        
        return inserted_ids
    
    def _scan_aoi_for_entry(
        self,
        candles_1h: pd.DataFrame,
        aoi: AOIZone,
        direction: TrendDirection,
        trend_snapshot: dict,
        trend_alignment: int,
        atr_1h: float,
    ) -> Optional[int]:
        """Scan a single AOI for entry pattern and store if found."""
        # Find entry pattern
        pattern = find_entry_pattern(candles_1h, aoi, direction)
        if not pattern:
            return None
        
        # Determine break and after-break indices
        if pattern.is_break_candle_last:
            break_index = len(pattern.candles) - 1
            after_break_index = None
        else:
            break_index = len(pattern.candles) - 2
            after_break_index = len(pattern.candles) - 1
        
        # Evaluate quality
        quality_result = evaluate_entry_quality(
            pattern.candles,
            aoi.lower,
            aoi.upper,
            direction,
            0,  # retest_idx
            break_index,
            after_break_index,
        )
        
        # Get entry price (close of last candle)
        entry_price = pattern.candles[-1].close
        signal_time = pattern.candles[-1].time
        
        # Check for duplicate - if exists, still try to add pre_entry_context
        existing_signal_id = self._get_existing_signal_id(signal_time)
        if existing_signal_id:
            # Signal exists, but still compute pre_entry_context if missing
            self._store_pre_entry_context(
                signal_id=existing_signal_id,
                signal_time=signal_time,
                direction=direction,
                aoi_low=aoi.lower,
                aoi_high=aoi.upper,
            )
            return None  # Signal wasn't newly inserted
        
        # Compute SL/TP distances using NEW logic:
        # effective_sl = max(structural, 2.5 ATR)
        # effective_tp = 2.25 × effective_sl
        sl_tp_data = compute_sl_tp_distances(
            direction=direction,
            entry_price=entry_price,
            aoi_low=aoi.lower,
            aoi_high=aoi.upper,
            atr_1h=atr_1h,
        )
        
        # Persist to database with new schema
        signal_id = self._store_signal(
            signal_time=signal_time,
            direction=direction,
            trend_snapshot=trend_snapshot,
            trend_alignment=trend_alignment,
            aoi=aoi,
            entry_price=entry_price,
            atr_1h=atr_1h,
            quality_result=quality_result,
            is_break_candle_last=pattern.is_break_candle_last,
            sl_tp_data=sl_tp_data,
        )
        
        # Compute and store pre-entry context if signal was stored
        if signal_id:
            self._store_pre_entry_context(
                signal_id=signal_id,
                signal_time=signal_time,
                direction=direction,
                aoi_low=aoi.lower,
                aoi_high=aoi.upper,
            )
        
        return signal_id
    
    def _signal_exists(self, signal_time: datetime) -> bool:
        """Check if a signal already exists for this symbol/time."""
        from database.executor import DBExecutor
        
        row = DBExecutor.fetch_one(
            CHECK_SIGNAL_EXISTS,
            (self._symbol, signal_time, SL_MODEL_VERSION, TP_MODEL_VERSION),
            context="check_signal_exists",
        )
        return row and row[0]
    
    def _get_existing_signal_id(self, signal_time: datetime) -> Optional[int]:
        """Get the ID of an existing signal, or None if it doesn't exist."""
        from database.executor import DBExecutor
        
        row = DBExecutor.fetch_one(
            GET_SIGNAL_ID,
            (self._symbol, signal_time, SL_MODEL_VERSION, TP_MODEL_VERSION),
            context="get_existing_signal_id",
        )
        return row[0] if row else None
    
    def _store_signal(
        self,
        signal_time: datetime,
        direction: TrendDirection,
        trend_snapshot: dict,
        trend_alignment: int,
        aoi: AOIZone,
        entry_price: float,
        atr_1h: float,
        quality_result,
        is_break_candle_last: bool,
        sl_tp_data,
    ) -> Optional[int]:
        """Persist signal to replay schema with new column structure."""
        from database.executor import DBExecutor
        from database.validation import DBValidator
        
        normalized_symbol = DBValidator.validate_symbol(self._symbol)
        if not normalized_symbol:
            return None
        
        def _persist(cursor):
            # Insert main entry signal with new schema
            cursor.execute(
                INSERT_REPLAY_ENTRY_SIGNAL,
                (
                    normalized_symbol,
                    signal_time,
                    direction.value,
                    self._get_trend_value(trend_snapshot, "4H"),
                    self._get_trend_value(trend_snapshot, "1D"),
                    self._get_trend_value(trend_snapshot, "1W"),
                    trend_alignment,
                    aoi.timeframe or "",
                    aoi.lower,
                    aoi.upper,
                    aoi.classification or "",
                    entry_price,
                    atr_1h,
                    quality_result.final_score,
                    quality_result.tier,
                    is_break_candle_last,
                    # Model versions
                    sl_tp_data.sl_model_version,
                    sl_tp_data.tp_model_version,
                    # SL distances
                    sl_tp_data.aoi_structural_sl_distance_price,
                    sl_tp_data.aoi_structural_sl_distance_atr,
                    sl_tp_data.effective_sl_distance_price,
                    sl_tp_data.effective_sl_distance_atr,
                    # TP distances
                    sl_tp_data.effective_tp_distance_atr,
                    sl_tp_data.effective_tp_distance_price,
                    # Trade profile
                    sl_tp_data.trade_profile,
                ),
            )
            signal_id = cursor.fetchone()[0]
            
            # Insert stage scores
            score_rows = [
                (
                    signal_id,
                    stage.stage_name,
                    stage.raw_score,
                    stage.weight,
                    stage.weighted_score,
                )
                for stage in quality_result.stage_scores
            ]
            
            if score_rows:
                cursor.executemany(INSERT_REPLAY_ENTRY_SIGNAL_SCORE, score_rows)
            
            return signal_id
        
        return DBExecutor.execute_transaction(_persist, context="store_replay_signal")
    
    def _get_trend_value(self, snapshot: dict, timeframe: str) -> str:
        """Get trend value as string."""
        trend = snapshot.get(timeframe)
        if trend is None:
            return "neutral"
        return trend.value if hasattr(trend, "value") else str(trend)
    
    def _store_pre_entry_context(
        self,
        signal_id: int,
        signal_time: datetime,
        direction: TrendDirection,
        aoi_low: float,
        aoi_high: float,
    ) -> None:
        """Compute and store pre-entry context for a signal."""
        from database.executor import DBExecutor
        
        # Compute pre-entry context
        calculator = PreEntryContextCalculator(
            candle_store=self._store,
            signal_time=signal_time,
            direction=direction,
            aoi_low=aoi_low,
            aoi_high=aoi_high,
        )
        
        context = calculator.compute()
        if context is None:
            return
        
        # Persist to database
        DBExecutor.execute_non_query(
            INSERT_REPLAY_PRE_ENTRY_CONTEXT,
            (
                signal_id,
                context.lookback_bars,
                context.impulse_bars,
                context.pre_atr,
                context.pre_atr_ratio,
                context.pre_range_atr,
                context.pre_range_to_atr_ratio,
                context.pre_net_move_atr,
                context.pre_total_move_atr,
                context.pre_efficiency,
                context.pre_counter_bar_ratio,
                context.pre_aoi_touch_count,
                context.pre_bars_in_aoi,
                context.pre_last_touch_distance_atr,
                context.pre_impulse_net_atr,
                context.pre_impulse_efficiency,
                context.pre_large_bar_ratio,
                context.pre_overlap_ratio,
                context.pre_wick_ratio,
            ),
            context="store_pre_entry_context",
        )


