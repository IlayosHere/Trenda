"""Entry signal detection for replay.

Reuses production gates and scoring logic to detect entry patterns,
then persists to the replay schema with idempotency checks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

import pandas as pd

from models import AOIZone, TrendDirection
from entry.pattern_finder import find_entry_pattern
from entry.gates import check_all_gates
from entry.scoring import calculate_score, ScoreResult
from utils.indicators import calculate_atr

from .market_state import SymbolState
from .candle_store import CandleStore
from .config import LOOKBACK_1H, SL_MODEL_VERSION, TP_MODEL_VERSION
from .replay_queries import (
    CHECK_SIGNAL_EXISTS,
    GET_SIGNAL_ID,
    GET_RELATED_SIGNAL_TRADE_ID,
    INSERT_REPLAY_ENTRY_SIGNAL,
)
from .lightweight_htf_context import compute_lightweight_htf_context


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
        
        Uses production gates and scoring - symbols that don't pass gates
        are skipped entirely (no AOI loop).
        
        Args:
            current_time: Current simulation time (1H candle close)
            state: Current market state (trends + AOIs)
            
        Returns:
            List of signal IDs that were inserted
        """
        inserted_ids = []
        
        # Get overall trend direction (with 2/3 TF support - not need to be consecutive)
        direction = self._get_replay_trend_direction(state)
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
        
        # Get trend alignment strength and conflicted TF
        trend_alignment = state.get_trend_alignment_strength(direction)
        conflicted_tf = self._get_conflicted_tf(state, direction)
        
        # === SYMBOL-LEVEL GATE CHECK (outside AOI loop) ===
        # Use last candle close as reference price for HTF context
        reference_price = candles_1h.iloc[-1]["close"]
        signal_time = candles_1h.iloc[-1]["time"]
        
        # Compute lightweight HTF context for gate checks (fast)
        htf_context = compute_lightweight_htf_context(
            candle_store=self._store,
            signal_time=signal_time,
            entry_price=reference_price,
            atr_1h=atr_1h,
            direction=direction,
        )
        
        if htf_context is None:
            return inserted_ids
        
        # Run production gates using entry module
        gate_result = check_all_gates(
            signal_time=signal_time,
            symbol=self._symbol,
            direction=direction,
            conflicted_tf=conflicted_tf,
            htf_range_position_daily=htf_context.htf_range_position_daily,
            htf_range_position_weekly=htf_context.htf_range_position_weekly,
            distance_to_next_htf_obstacle_atr=htf_context.distance_to_next_htf_obstacle_atr,
        )
        
        if not gate_result.passed:
            # Symbol fails gates, skip all AOIs
            return inserted_ids
        
        # Calculate score ONCE per symbol (using production scoring)
        score_result = calculate_score(
            direction=direction,
            htf_range_position_daily=htf_context.htf_range_position_daily,
            htf_range_position_weekly=htf_context.htf_range_position_weekly,
        )
        
        if not score_result.passed:
            # Score too low, skip all AOIs
            return inserted_ids
        
        # Get tradable AOIs
        tradable_aois = state.get_tradable_aois()
        
        # === AOI LOOP (only pattern finding and signal creation) ===
        for aoi in tradable_aois:
            signal_id = self._scan_aoi_for_entry(
                candles_1h=candles_1h,
                aoi=aoi,
                direction=direction,
                trend_snapshot=trend_snapshot,
                trend_alignment=trend_alignment,
                atr_1h=atr_1h,
                conflicted_tf=conflicted_tf,
                score_result=score_result,
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
        conflicted_tf: Optional[str],
        score_result: ScoreResult,
    ) -> Optional[int]:
        """Scan a single AOI for entry pattern and store if found.
        
        Gates and scoring have already passed at symbol level.
        Streamlined for performance - only stores essential signal data.
        """
        # Find entry pattern (AOI-specific)
        pattern = find_entry_pattern(candles_1h, aoi, direction)
        if not pattern:
            return None
        
        # Determine break index
        if pattern.is_break_candle_last:
            break_index = len(pattern.candles) - 1
        else:
            break_index = len(pattern.candles) - 2
        
        # Use production score (already computed and passed)
        final_score = score_result.total_score
        tier = "scored" if score_result.passed else "unscored"
        
        # Get entry price (close of last candle)
        entry_price = pattern.candles[-1].close
        signal_time = pattern.candles[-1].time
        
        # Check for duplicate - if exists, skip
        existing_signal_id = self._get_existing_signal_id(signal_time)
        if existing_signal_id:
            return None  # Signal already exists
        
        # Compute minimal entry_signal fields (fast)
        retest_idx = 0  # First candle is retest
        max_retest_penetration_atr = self._compute_max_retest_penetration(
            pattern.candles, retest_idx, break_index, aoi, direction, atr_1h
        )
        bars_between_retest_and_break = break_index - retest_idx - 1 if break_index > retest_idx else 0
        hour_of_day_utc = signal_time.hour
        session_bucket = self._get_session_bucket(signal_time.hour)
        
        # Generate trade_id
        trade_id = self._get_or_generate_trade_id(signal_time)
        
        # Persist to database (minimal fields)
        signal_id = self._store_signal(
            signal_time=signal_time,
            direction=direction,
            trend_snapshot=trend_snapshot,
            trend_alignment=trend_alignment,
            aoi=aoi,
            entry_price=entry_price,
            atr_1h=atr_1h,
            final_score=final_score,
            tier=tier,
            is_break_candle_last=pattern.is_break_candle_last,
            sl_model_version=SL_MODEL_VERSION,
            tp_model_version=TP_MODEL_VERSION,
            conflicted_tf=conflicted_tf,
            max_retest_penetration_atr=max_retest_penetration_atr,
            bars_between_retest_and_break=bars_between_retest_and_break,
            hour_of_day_utc=hour_of_day_utc,
            session_bucket=session_bucket,
            aoi_touch_count_since_creation=0,  # Skip expensive computation
            trade_id=trade_id,
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
        final_score,
        tier,
        is_break_candle_last: bool,
        sl_model_version: str,
        tp_model_version: str,
        conflicted_tf: Optional[str],
        max_retest_penetration_atr: Optional[float],
        bars_between_retest_and_break: int,
        hour_of_day_utc: int,
        session_bucket: str,
        aoi_touch_count_since_creation: Optional[int],
        trade_id: str,
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
                    final_score,
                    tier,
                    is_break_candle_last,
                    # Model versions
                    sl_model_version,
                    tp_model_version,
                    # Conflicted TF
                    conflicted_tf,
                    # Entry metrics
                    max_retest_penetration_atr,
                    bars_between_retest_and_break,
                    hour_of_day_utc,
                    session_bucket,
                    aoi_touch_count_since_creation,
                    trade_id,
                ),
            )
            signal_id = cursor.fetchone()[0]
            
            # Stage scores no longer computed (quality system deprecated)
            
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

    def _compute_pre_entry_context_v2(
        self,
        signal_time: datetime,
        retest_time: datetime,
        direction: TrendDirection,
        entry_price: float,
        atr_1h: float,
        aoi_low: float,
        aoi_high: float,
        aoi_timeframe: str,
        state: SymbolState,
        break_candle: Optional[dict] = None,
        retest_candle: Optional[dict] = None,
    ) -> Optional[PreEntryContextV2Data]:
        """Compute pre-entry context V2 (market environment) for gate checks."""
        calculator = PreEntryContextV2Calculator(
            candle_store=self._store,
            signal_time=signal_time,
            retest_time=retest_time,
            direction=direction,
            entry_price=entry_price,
            atr_1h=atr_1h,
            aoi_low=aoi_low,
            aoi_high=aoi_high,
            aoi_timeframe=aoi_timeframe,
            state=state,
            break_candle=break_candle,
            retest_candle=retest_candle,
        )
        return calculator.compute()

    def _persist_pre_entry_context_v2(
        self,
        signal_id: int,
        context: PreEntryContextV2Data,
    ) -> None:
        """Persist already-computed pre-entry context V2 to database."""
        from database.executor import DBExecutor
        
        DBExecutor.execute_non_query(
            INSERT_REPLAY_PRE_ENTRY_CONTEXT_V2,
            (
                signal_id,
                context.htf_range_position_daily,
                context.htf_range_position_weekly,
                context.distance_to_daily_high_atr,
                context.distance_to_daily_low_atr,
                context.distance_to_weekly_high_atr,
                context.distance_to_weekly_low_atr,
                context.distance_to_4h_high_atr,
                context.distance_to_4h_low_atr,
                context.distance_to_next_htf_obstacle_atr,
                context.prev_session_high,
                context.prev_session_low,
                context.distance_to_prev_session_high_atr,
                context.distance_to_prev_session_low_atr,
                context.trend_age_bars_1h,
                context.trend_age_impulses,
                context.recent_trend_payoff_atr_24h,
                context.recent_trend_payoff_atr_48h,
                context.session_directional_bias,
                context.aoi_time_since_last_touch,
                context.aoi_last_reaction_strength,
                context.distance_from_last_impulse_atr,
                context.htf_range_size_daily_atr,
                context.htf_range_size_weekly_atr,
                context.aoi_midpoint_range_position_daily,
                context.aoi_midpoint_range_position_weekly,
                # New break/retest candle metrics
                context.break_impulse_range_atr,
                context.break_impulse_body_atr,
                context.break_close_location,
                context.retest_candle_body_penetration,
            ),
            context="store_pre_entry_context_v2",
        )
    
    def _get_replay_trend_direction(self, state: SymbolState) -> Optional[TrendDirection]:
        """Get trend direction with consecutive TF alignment requirement.
        
        For replay, we require at least 2 consecutive TFs to align:
        - 4H + 1D aligned (1W can differ)
        - 1D + 1W aligned (4H can differ)
        - All 3 TFs aligned
        
        Returns:
            TrendDirection if consecutive alignment found, None otherwise
        """
        trend_4h = state.trend_4h
        trend_1d = state.trend_1d
        trend_1w = state.trend_1w
        
        # Check all 3 aligned
        if trend_4h == trend_1d == trend_1w:
            if trend_4h in (TrendDirection.BULLISH, TrendDirection.BEARISH):
                return trend_4h
        
        # Check 4H + 1D aligned (consecutive)
        if trend_4h == trend_1d:
            if trend_4h in (TrendDirection.BULLISH, TrendDirection.BEARISH):
                return trend_4h
        
        # Check 1D + 1W aligned (consecutive)
        if trend_1d == trend_1w:
            if trend_1d in (TrendDirection.BULLISH, TrendDirection.BEARISH):
                return trend_1d
        
        # No consecutive alignment
        return None
    
    def _get_conflicted_tf(self, state: SymbolState, direction: TrendDirection) -> Optional[str]:
        """Get the conflicted TF (the one that disagrees with direction).
        
        With consecutive alignment requirement, only 4H or 1W can conflict:
        - If 4H + 1D aligned → 1W conflicts
        - If 1D + 1W aligned → 4H conflicts
        - If all 3 aligned → None
        
        Returns:
            None if all 3 TFs aligned
            '4H' if 4H differs from direction
            '1W' if 1W differs
        """
        trend_4h = state.trend_4h
        trend_1d = state.trend_1d
        trend_1w = state.trend_1w
        
        # All 3 aligned
        if trend_4h == trend_1d == trend_1w:
            return None
        
        # 4H + 1D aligned, 1W differs
        if trend_4h == trend_1d == direction:
            return "1W"
        
        # 1D + 1W aligned, 4H differs
        if trend_1d == trend_1w == direction:
            return "4H"
        
        return None
    
    def _compute_max_retest_penetration(
        self,
        candles,
        retest_idx: int,
        break_idx: int,
        aoi: AOIZone,
        direction: TrendDirection,
        atr_1h: float,
    ) -> Optional[float]:
        """Compute max penetration into AOI during retest phase."""
        if atr_1h <= 0 or retest_idx >= break_idx:
            return None
        
        max_penetration = 0.0
        is_long = direction == TrendDirection.BULLISH
        
        for i in range(retest_idx, break_idx + 1):
            candle = candles[i]
            if is_long:
                # Bullish: penetration = how far low goes below aoi_high
                penetration = max(0, aoi.upper - candle.low)
            else:
                # Bearish: penetration = how far high goes above aoi_low
                penetration = max(0, candle.high - aoi.lower)
            
            max_penetration = max(max_penetration, penetration)
        
        return max_penetration / atr_1h if max_penetration > 0 else 0.0
    
    def _get_session_bucket(self, hour: int) -> str:
        """Get session bucket from UTC hour."""
        if 4 <= hour <= 6:
            return "pre_london"
        elif 7 <= hour <= 11:
            return "london"
        elif 12 <= hour <= 16:
            return "ny"
        else:
            return "post_ny"
    
    def _compute_aoi_touch_count(self, aoi: AOIZone, signal_time: datetime) -> Optional[int]:
        """Count AOI touches since creation on AOI's timeframe."""
        timeframe = aoi.timeframe
        if not timeframe:
            return None
        
        # Get appropriate candles for AOI's timeframe
        if timeframe == "4H":
            tf_candles = self._store.get_4h_candles().get_candles_up_to(signal_time)
        elif timeframe == "1D":
            tf_candles = self._store.get_1d_candles().get_candles_up_to(signal_time)
        else:
            return None
        
        if tf_candles is None or tf_candles.empty:
            return None
        
        # Count candles that overlap AOI
        touch_count = 0
        for _, row in tf_candles.iterrows():
            if row["high"] >= aoi.lower and row["low"] <= aoi.upper:
                touch_count += 1
        
        return touch_count
    
    def _get_or_generate_trade_id(self, signal_time: datetime) -> str:
        """Get existing trade_id from a related signal 1 hour ago, or generate new one.
        
        Groups break + after-break signals together with the same trade_id.
        Format: {symbol}_{timestamp} where timestamp is the first signal's time.
        """
        from database.executor import DBExecutor
        
        # Check if there's a signal from 1 hour ago with a trade_id
        row = DBExecutor.fetch_one(
            GET_RELATED_SIGNAL_TRADE_ID,
            (self._symbol, signal_time),
            context="get_related_trade_id",
        )
        
        if row and row[0]:
            return row[0]  # Use existing trade_id
        
        # Generate new trade_id: symbol_timestamp
        timestamp_str = signal_time.strftime("%Y%m%d_%H%M")
        return f"{self._symbol}_{timestamp_str}"
