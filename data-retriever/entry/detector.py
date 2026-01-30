from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple

import pandas as pd

from configuration import FOREX_PAIRS, TIMEFRAMES, require_analysis_params, SIGNAL_SCORE_THRESHOLD, MT5_ORDER_COMMENT
from entry.pattern_finder import find_entry_pattern
from entry.gates import check_all_gates
from entry.gates.config import SL_MODEL_NAME, SL_BUFFER_ATR, RR_MULTIPLE
from entry.htf_context import compute_htf_context, get_conflicted_timeframe, HTFContext
from entry.scoring import calculate_score, ScoreResult
from entry.live_execution import compute_execution_data, ExecutionData
from entry.signal_repository import store_entry_signal_with_symbol
from entry.failed_signal_repository import store_failed_signal, FailedSignalData
from aoi.aoi_repository import fetch_tradable_aois
from externals.data_fetcher import fetch_data
from externals.meta_trader import (
    initialize_mt5,
    place_order,
    can_execute_trade,
    verify_position_consistency,
    mt5,
)

from models import AOIZone, TrendDirection
from models.market import SignalData
from trend.bias import get_overall_trend, get_trend_by_timeframe
from utils.indicators import calculate_atr
from logger import get_logger

logger = get_logger(__name__)


DEFAULT_TREND_ALIGNMENT: tuple[str, ...] = ("4H", "1D", "1W")


class _FailureContext:
    """Accumulates context during symbol processing for failure tracking."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.signal_time = None
        self.reference_price: Optional[float] = None
        self.direction: Optional[TrendDirection] = None
        self.aois: Optional[list] = None
        self.atr_1h: Optional[float] = None
        self.htf_context: Optional[HTFContext] = None
        self.score_result: Optional[ScoreResult] = None
        self.conflicted_tf: Optional[str] = None
        
        # Failure info (set when failure occurs)
        self.failed_gate: Optional[str] = None
        self.fail_reason: Optional[str] = None
    
    def set_failure(self, gate: str, reason: str) -> None:
        """Mark this context as failed."""
        self.failed_gate = gate
        self.fail_reason = reason
    
    def has_failed(self) -> bool:
        return self.failed_gate is not None
    
    def store_if_failed(self) -> None:
        """Store failure to DB if this context represents a failure."""
        if not self.has_failed():
            return
        
        # Convert AOIs to JSON-serializable format
        tradable_aois = None
        if self.aois:
            tradable_aois = [
                {"aoi_high": aoi.upper, "aoi_low": aoi.lower, "timeframe": aoi.timeframe}
                for aoi in self.aois
            ]
        
        data = FailedSignalData(
            symbol=self.symbol,
            failed_signal_time=self.signal_time or pd.Timestamp.now(tz='UTC'),
            failed_gate=self.failed_gate,
            fail_reason=self.fail_reason,
            direction=self.direction,
            tradable_aois=tradable_aois,
            reference_price=self.reference_price,
            atr_1h=self.atr_1h,
            htf_score=self.score_result.htf_score if self.score_result else None,
            obstacle_score=self.score_result.obstacle_score if self.score_result else None,
            total_score=self.score_result.total_score if self.score_result else None,
            sl_model=SL_MODEL_NAME,
            htf_range_position_daily=self.htf_context.htf_range_position_daily if self.htf_context else None,
            htf_range_position_weekly=self.htf_context.htf_range_position_weekly if self.htf_context else None,
            distance_to_next_htf_obstacle_atr=self.htf_context.distance_to_next_htf_obstacle_atr if self.htf_context else None,
            conflicted_tf=self.conflicted_tf,
        )
        
        store_failed_signal(data)


def run_1h_entry_scan_job(
    timeframe: str,
    trend_alignment_timeframes: Sequence[str] = DEFAULT_TREND_ALIGNMENT,
) -> None:
    """Scheduled 1H entry scan across all forex pairs and tradable AOIs."""

    mt5_timeframe = TIMEFRAMES.get(timeframe)
    lookback = require_analysis_params(timeframe).lookback

    num_symbols = len(FOREX_PAIRS)
    logger.info(f"\n--- 🔍 Starting {timeframe} entry scan for {num_symbols} symbols ---")
    
    # Ensure MT5 is initialized before starting the scan
    if mt5 and not initialize_mt5():
        logger.error("❌ Failed to initialize MT5. Aborting scan job.")
        return

    for symbol in FOREX_PAIRS:
        logger.info(f"  -> Checking {symbol}...")
        ctx = _FailureContext(symbol)
        
        try:
            _process_symbol(
                symbol=symbol,
                timeframe=timeframe,
                mt5_timeframe=mt5_timeframe,
                lookback=lookback,
                trend_alignment_timeframes=trend_alignment_timeframes,
                ctx=ctx,
            )
        finally:
            # Store failure if one occurred during processing
            ctx.store_if_failed()


def _process_symbol(
    symbol: str,
    timeframe: str,
    mt5_timeframe,
    lookback: int,
    trend_alignment_timeframes: Sequence[str],
    ctx: _FailureContext,
) -> None:
    """Process a single symbol for entry signals. Updates ctx with failure info if needed."""
    
    # 1. Prevent duplicate trades or over-trading: skip if constraints are met
    is_blocked, reason = can_execute_trade(symbol)
    if is_blocked:
        logger.info(f"    ⏩ Skipped {symbol}: {reason}")
        # Note: We don't log TRADE_BLOCKED as a "failure" - it's expected behavior
        return

    # 2. Fetch candle data
    candles = fetch_data(
        symbol,
        mt5_timeframe,
        int(lookback),
        timeframe_label=timeframe,
    )
    if candles is None:
        logger.error(f"  ❌ Skipping {symbol}: no candle data returned for timeframe {timeframe}.")
        ctx.set_failure("NO_CANDLES", f"No candle data returned for timeframe {timeframe}")
        return

    # Extract reference values early for failure context
    ctx.reference_price = candles.iloc[-1]["close"]
    ctx.signal_time = candles.iloc[-1]["time"]

    # 3. Data sufficiency check
    if len(candles) < lookback:
        logger.warning(f"    ⏩ Skipped {symbol}: Insufficient data ({len(candles)} < {lookback} required).")
        ctx.set_failure("INSUFFICIENT_DATA", f"Insufficient data ({len(candles)} < {lookback} required)")
        return

    # Get direction from trend alignment
    trend_snapshot = _collect_trend_snapshot(trend_alignment_timeframes, symbol)
    ctx.direction = TrendDirection.from_raw(
        get_overall_trend(trend_alignment_timeframes, symbol)
    )
    if ctx.direction is None:
        ctx.set_failure("NO_DIRECTION", "Neutral or undefined trend alignment")
        return

    ctx.aois = fetch_tradable_aois(symbol)
    if not ctx.aois:
        ctx.set_failure("NO_AOIS", "No tradable AOIs found")
        return

    # === SYMBOL-LEVEL CALCULATIONS (outside AOI loop) ===
    ctx.atr_1h = calculate_atr(candles)
    if ctx.atr_1h <= 0:
        logger.warning(f"    ⏩ Skipped {symbol}: ATR calculation failed (zero ATR).")
        ctx.set_failure("ZERO_ATR", "ATR calculation failed (zero ATR)")
        return

    # Compute HTF context ONCE per symbol
    ctx.htf_context = compute_htf_context(
        symbol=symbol,
        entry_price=ctx.reference_price,
        atr_1h=ctx.atr_1h,
        direction=ctx.direction,
    )
    
    # Determine conflicted TF ONCE per symbol
    ctx.conflicted_tf = get_conflicted_timeframe(
        trend_4h=_get_trend_value(trend_snapshot, "4H"),
        trend_1d=_get_trend_value(trend_snapshot, "1D"),
        trend_1w=_get_trend_value(trend_snapshot, "1W"),
        direction=ctx.direction,
    )
    
    # Run symbol-level gates ONCE (time, TF conflict, HTF alignment, obstacle)
    gate_result = check_all_gates(
        signal_time=ctx.signal_time,
        symbol=symbol,
        direction=ctx.direction,
        conflicted_tf=ctx.conflicted_tf,
        htf_range_position_daily=ctx.htf_context.htf_range_position_daily,
        htf_range_position_weekly=ctx.htf_context.htf_range_position_weekly,
        distance_to_next_htf_obstacle_atr=ctx.htf_context.distance_to_next_htf_obstacle_atr,
    )
    
    if not gate_result.passed:
        logger.info(f"    ⏩ Skipped {symbol}: {gate_result.failed_gate} - {gate_result.failed_reason}")
        ctx.set_failure(gate_result.failed_gate, gate_result.failed_reason)
        return
    
    # Calculate score ONCE per symbol
    ctx.score_result = calculate_score(
        direction=ctx.direction,
        htf_range_position_daily=ctx.htf_context.htf_range_position_daily,
        htf_range_position_weekly=ctx.htf_context.htf_range_position_weekly,
    )
    
    if not ctx.score_result.passed:
        logger.info(f"    ⏩ Skipped {symbol}: Score {ctx.score_result.total_score:.2f} < {SIGNAL_SCORE_THRESHOLD} threshold")
        ctx.set_failure("SCORE_BELOW_THRESHOLD", f"Score {ctx.score_result.total_score:.2f} < {SIGNAL_SCORE_THRESHOLD} threshold")
        return

    # === AOI-LEVEL LOOP (only pattern finding and signal creation) ===
    signal_found = False
    for aoi in ctx.aois:
        signal = _scan_aoi_for_pattern(
            symbol=symbol,
            direction=ctx.direction,
            aoi=aoi,
            candles_1h=candles,
            atr_1h=ctx.atr_1h,
            htf_context=ctx.htf_context,
            score_result=ctx.score_result,
            conflicted_tf=ctx.conflicted_tf,
        )
        if signal:
            signal_found = True
            # Compute live execution data FIRST
            execution = compute_execution_data(
                symbol=symbol,
                direction=ctx.direction,
                aoi_low=aoi.lower,
                aoi_high=aoi.upper,
                atr_1h=ctx.atr_1h,
                signal_candle_close=ctx.reference_price,
            )
            
            if not execution:
                logger.warning(f"    ⚠️ Pattern found but no live execution data for {symbol}")
                continue

            # TODO: ADD HERE WHATSAPP NOTIFICATIONS with execution data
            
            # Place MT5 order (only if MT5 module is available)
            if mt5:
                if ctx.direction == TrendDirection.BULLISH:
                    order_type = mt5.ORDER_TYPE_BUY
                elif ctx.direction == TrendDirection.BEARISH:
                    order_type = mt5.ORDER_TYPE_SELL
                else:
                     logger.error(f"    ❌ Invalid trend direction for {symbol}: {ctx.direction}. Skipping trade.")
                     continue

                order_result = place_order(
                    symbol=symbol,
                    order_type=order_type,
                    price=execution.entry_price,
                    volume=execution.lot_size,
                    sl=execution.sl_price,
                    tp=execution.tp_price,
                    comment=MT5_ORDER_COMMENT,
                )
                
                if order_result is None or (hasattr(order_result, 'retcode') and order_result.retcode != mt5.TRADE_RETCODE_DONE):
                    logger.error(f"    ❌ MT5 order failed for {symbol}. Skipping signal storage.")
                    continue
                
                logger.info(
                    f"    💰 MT5 ORDER PLACED: Ticket #{order_result.order} | "
                    f"{ctx.direction.value} {symbol} @ {execution.entry_price:.5f}"
                )
                
                # Verify position consistency (SL/TP, Volume, Price)
                is_consistent = verify_position_consistency(
                    ticket=order_result.order,
                    expected_sl=execution.sl_price,
                    expected_tp=execution.tp_price,
                    expected_volume=execution.lot_size,
                    expected_price=execution.entry_price
                )
                
                if not is_consistent:
                    logger.error(f"    ❌ Verification failed for {symbol}: Position mismatch or excessive slippage. Trade CLOSED.")
                    # Stop processing other AOIs for this symbol to avoid rapid re-entry (churning)
                    break
            else:
                logger.warning(f"    ⚠️ MT5 not available. Skipping order placement for {symbol}.")
                logger.error("    ❌ MT5 module missing. Skipping signal storage.")
                continue
            
            # Populate SignalData with live execution values
            signal.entry_price = execution.entry_price
            signal.sl_distance_atr = execution.sl_distance_atr
            signal.tp_distance_atr = execution.tp_distance_atr
            signal.actual_rr = execution.actual_rr
            signal.price_drift = execution.price_drift
            
            # NOW store signal with complete data
            entry_id = store_entry_signal_with_symbol(symbol, signal)
            if entry_id:
                logger.info(f"    ✅ Signal stored in DB (ID: {entry_id}, Score: {signal.total_score:.2f}) ")
            else:
                logger.error(f"    ❌ Failed to store signal for {symbol} in database, but MT5 trade is ACTIVE.")

            # Always log execution details if we reached this point (order was placed)
            logger.info(
                f"       📊 EXECUTION: {execution.direction.value} {execution.symbol} "
                f"@ {execution.entry_price:.5f} | "
                f"Lot: {execution.lot_size} | "
                f"SL: {execution.sl_price:.5f} | "
                f"TP: {execution.tp_price:.5f}"
            )
            
            # Stop checking other AOIs for this symbol once an order is placed
            break
    
    # If no pattern was found in any AOI after passing all gates and scoring
    if not signal_found:
        ctx.set_failure("NO_PATTERN", f"No entry pattern found in {len(ctx.aois)} tradable AOIs")


def _collect_trend_snapshot(
    timeframes: Sequence[str], symbol: str
) -> Mapping[str, Optional[TrendDirection]]:
    return {tf: get_trend_by_timeframe(symbol, tf) for tf in timeframes}


def _get_trend_value(
    trend_snapshot: Mapping[str, Optional[TrendDirection]], 
    timeframe: str
) -> str:
    """Get the trend value as a string for a specific timeframe."""
    trend = trend_snapshot.get(timeframe)
    return trend.value if trend else "neutral"


def _scan_aoi_for_pattern(
    symbol: str,
    direction: TrendDirection,
    aoi: AOIZone,
    candles_1h: pd.DataFrame,
    atr_1h: float,
    htf_context: HTFContext,
    score_result: ScoreResult,
    conflicted_tf: Optional[str],
) -> Optional[SignalData]:
    """Find pattern in AOI and build SignalData if found. Gates/scoring already passed.
    
    Note: entry_price, sl_distance_atr, tp_distance_atr are populated
    later by live_execution after trade execution.
    """
    
    # Pattern finding is AOI-specific
    pattern = find_entry_pattern(candles_1h, aoi, direction)
    if not pattern:
        return None

    signal_time = pattern.candles[-1].time

    return SignalData(
        candles=pattern.candles,
        signal_time=signal_time,
        direction=direction,
        # AOI snapshot (simplified)
        aoi_timeframe=aoi.timeframe,
        aoi_low=aoi.lower,
        aoi_high=aoi.upper,
        # Entry context (populated after live execution)
        entry_price=None,  # Will be set by live execution
        atr_1h=atr_1h,
        # Scoring (pre-computed)
        htf_score=score_result.htf_score,
        obstacle_score=score_result.obstacle_score,
        total_score=score_result.total_score,
        # SL/TP configuration (calculated with live price)
        sl_model=SL_MODEL_NAME,
        sl_distance_atr=None,  # Will be set by live execution
        tp_distance_atr=None,  # Will be set by live execution
        rr_multiple=RR_MULTIPLE,
        # Meta
        is_break_candle_last=pattern.is_break_candle_last,
        # HTF context (pre-computed)
        htf_range_position_daily=htf_context.htf_range_position_daily,
        htf_range_position_weekly=htf_context.htf_range_position_weekly,
        distance_to_next_htf_obstacle_atr=htf_context.distance_to_next_htf_obstacle_atr,
        conflicted_tf=conflicted_tf,
    )
