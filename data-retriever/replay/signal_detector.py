"""Entry signal detection for replay.

Reuses production logic to detect entry patterns and evaluate quality,
then persists to the replay schema with idempotency checks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

import pandas as pd

from models import AOIZone, TrendDirection
from models.market import Candle, SignalData
from entry.pattern_finder import find_entry_pattern
from entry.quality import evaluate_entry_quality
from entry.sl_calculator import compute_aoi_sl_distances
from utils.indicators import calculate_atr
from utils.candles import prepare_candles
from database.executor import DBExecutor
from database.validation import DBValidator

from .market_state import SymbolState
from .candle_store import CandleStore
from .config import LOOKBACK_1H, TIMEFRAME_1H
from .replay_queries import (
    CHECK_SIGNAL_EXISTS,
    INSERT_REPLAY_ENTRY_SIGNAL,
    INSERT_REPLAY_ENTRY_SIGNAL_SCORE,
)


class ReplaySignalDetector:
    """Detects entry signals during replay using production logic.
    
    For each 1H candle close:
    1. Gets current 1H candles (up to lookback)
    2. Gets tradable AOIs from current market state
    3. Finds entry patterns for each AOI
    4. Evaluates quality and computes SL distances
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
        
        # Check for duplicate
        if self._signal_exists(signal_time):
            return None
        
        # Compute SL distances
        sl_data = compute_aoi_sl_distances(
            direction=direction,
            entry_price=entry_price,
            aoi_low=aoi.lower,
            aoi_high=aoi.upper,
            atr_1h=atr_1h,
        )
        
        # Build SignalData
        signal = SignalData(
            candles=pattern.candles,
            signal_time=signal_time,
            direction=direction,
            trend_4h=self._get_trend_value(trend_snapshot, "4H"),
            trend_1d=self._get_trend_value(trend_snapshot, "1D"),
            trend_1w=self._get_trend_value(trend_snapshot, "1W"),
            trend_alignment_strength=trend_alignment,
            aoi_timeframe=aoi.timeframe or "",
            aoi_low=aoi.lower,
            aoi_high=aoi.upper,
            aoi_classification=aoi.classification or "",
            entry_price=entry_price,
            atr_1h=atr_1h,
            quality_result=quality_result,
            is_break_candle_last=pattern.is_break_candle_last,
            aoi_sl_tolerance_atr=sl_data.aoi_sl_tolerance_atr,
            aoi_raw_sl_distance_price=sl_data.aoi_raw_sl_distance_price,
            aoi_raw_sl_distance_atr=sl_data.aoi_raw_sl_distance_atr,
            aoi_effective_sl_distance_price=sl_data.aoi_effective_sl_distance_price,
            aoi_effective_sl_distance_atr=sl_data.aoi_effective_sl_distance_atr,
        )
        
        # Persist to database
        return self._store_signal(signal)
    
    def _signal_exists(self, signal_time: datetime) -> bool:
        """Check if a signal already exists for this symbol/time."""
        row = DBExecutor.fetch_one(
            CHECK_SIGNAL_EXISTS,
            (self._symbol, signal_time),
            context="check_signal_exists",
        )
        return row and row[0]
    
    def _store_signal(self, signal: SignalData) -> Optional[int]:
        """Persist signal to replay schema."""
        normalized_symbol = DBValidator.validate_symbol(self._symbol)
        if not normalized_symbol:
            return None
        
        def _persist(cursor):
            # Insert main entry signal
            cursor.execute(
                INSERT_REPLAY_ENTRY_SIGNAL,
                (
                    normalized_symbol,
                    signal.signal_time,
                    signal.direction.value,
                    signal.trend_4h,
                    signal.trend_1d,
                    signal.trend_1w,
                    signal.trend_alignment_strength,
                    signal.aoi_timeframe,
                    signal.aoi_low,
                    signal.aoi_high,
                    signal.aoi_classification,
                    signal.entry_price,
                    signal.atr_1h,
                    signal.quality_result.final_score,
                    signal.quality_result.tier,
                    signal.is_break_candle_last,
                    signal.aoi_sl_tolerance_atr,
                    signal.aoi_raw_sl_distance_price,
                    signal.aoi_raw_sl_distance_atr,
                    signal.aoi_effective_sl_distance_price,
                    signal.aoi_effective_sl_distance_atr,
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
                for stage in signal.quality_result.stage_scores
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
