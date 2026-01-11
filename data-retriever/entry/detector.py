from __future__ import annotations

from typing import Mapping, Optional, Sequence

import pandas as pd

from configuration import FOREX_PAIRS, TIMEFRAMES, require_analysis_params
from entry.pattern_finder import find_entry_pattern
from entry.gates import check_all_gates
from entry.gates.config import SL_MODEL_NAME, SL_BUFFER_ATR, RR_MULTIPLE
from entry.htf_context import compute_htf_context, get_conflicted_timeframe, HTFContext
from entry.scoring import calculate_score, ScoreResult
from entry.live_execution import compute_execution_data, ExecutionData
from entry.signal_repository import store_entry_signal_with_symbol
from aoi.aoi_repository import fetch_tradable_aois
from externals.data_fetcher import fetch_data
from externals.mt5_handler import place_order, is_trade_open, verify_sl_tp_consistency

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
from models import AOIZone, TrendDirection
from models.market import SignalData
from trend.bias import get_overall_trend, get_trend_by_timeframe
from utils.indicators import calculate_atr
from logger import get_logger

logger = get_logger(__name__)


DEFAULT_TREND_ALIGNMENT: tuple[str, ...] = ("4H", "1D", "1W")


def run_1h_entry_scan_job(
    timeframe: str,
    trend_alignment_timeframes: Sequence[str] = DEFAULT_TREND_ALIGNMENT,
) -> None:
    """Scheduled 1H entry scan across all forex pairs and tradable AOIs."""

    mt5_timeframe = TIMEFRAMES.get(timeframe)
    lookback = require_analysis_params(timeframe).lookback

    logger.info(f"\n--- 🔍 Running {timeframe} entry scan across symbols ---")

    for symbol in FOREX_PAIRS:
        logger.info(f"  -> Checking {symbol}...")
        candles = fetch_data(
            symbol,
            mt5_timeframe,
            int(lookback),
            timeframe_label=timeframe,
        )
        if candles is None:
            logger.error(
                f"  ❌ Skipping {symbol}: no candle data returned for timeframe {timeframe}."
            )
            continue
        if candles.empty:
            logger.error(
                f"  ❌ Skipping {symbol}: no closed candles available after trimming."
            )
            continue

        # Get direction from trend alignment
        trend_snapshot = _collect_trend_snapshot(trend_alignment_timeframes, symbol)
        direction = TrendDirection.from_raw(
            get_overall_trend(trend_alignment_timeframes, symbol)
        )
        if direction is None:
            continue

        aois = fetch_tradable_aois(symbol)
        if not aois:
            continue

        # Prevent duplicate trades or over-trading: skip if constraints are met
        is_blocked, reason = is_trade_open(symbol)
        if is_blocked:
            logger.info(f"    ⏩ Skipped {symbol}: {reason}")
            continue

        # === SYMBOL-LEVEL CALCULATIONS (outside AOI loop) ===
        atr_1h = calculate_atr(candles)
        if atr_1h <= 0:
            logger.warning(f"    ⏩ Skipped {symbol}: ATR calculation failed (zero ATR).")
            continue

        trend_alignment_strength = _calculate_trend_alignment_strength(trend_snapshot, direction)
        
        # Use last candle as reference for HTF context (price differences between AOIs are minimal)
        reference_price = candles.iloc[-1]["close"]
        signal_time = candles.iloc[-1]["time"]
        
        # Compute HTF context ONCE per symbol
        htf_context = compute_htf_context(
            symbol=symbol,
            entry_price=reference_price,
            atr_1h=atr_1h,
            direction=direction,
        )
        
        # Determine conflicted TF ONCE per symbol
        conflicted_tf = get_conflicted_timeframe(
            trend_4h=_get_trend_value(trend_snapshot, "4H"),
            trend_1d=_get_trend_value(trend_snapshot, "1D"),
            trend_1w=_get_trend_value(trend_snapshot, "1W"),
            direction=direction,
        )
        
        # Run symbol-level gates ONCE (time, TF conflict, HTF alignment, obstacle)
        gate_result = check_all_gates(
            signal_time=signal_time,
            symbol=symbol,
            direction=direction,
            conflicted_tf=conflicted_tf,
            htf_range_position_daily=htf_context.htf_range_position_daily,
            htf_range_position_weekly=htf_context.htf_range_position_weekly,
            distance_to_next_htf_obstacle_atr=htf_context.distance_to_next_htf_obstacle_atr,
        )
        
        if not gate_result.passed:
            logger.info(
                f"    ⏩ Skipped {symbol}: {gate_result.failed_gate} - {gate_result.failed_reason}"
            )
            continue
        
        # Calculate score ONCE per symbol
        score_result = calculate_score(
            direction=direction,
            htf_range_position_daily=htf_context.htf_range_position_daily,
            htf_range_position_weekly=htf_context.htf_range_position_weekly,
        )
        
        if not score_result.passed:
            logger.info(
                f"    ⏩ Skipped {symbol}: Score {score_result.total_score:.2f} < 4.0 threshold"
            )
            continue

        # === AOI-LEVEL LOOP (only pattern finding and signal creation) ===
        for aoi in aois:
            signal = _scan_aoi_for_pattern(
                symbol=symbol,
                direction=direction,
                aoi=aoi,
                candles_1h=candles,
                atr_1h=atr_1h,
                htf_context=htf_context,
                score_result=score_result,
                conflicted_tf=conflicted_tf,
            )
            if signal:
                # Compute live execution data FIRST
                execution = compute_execution_data(
                    symbol=symbol,
                    direction=direction,
                    aoi_low=aoi.lower,
                    aoi_high=aoi.upper,
                    atr_1h=atr_1h,
                )
                
                if not execution:
                    logger.warning(
                        f"    ⚠️ Pattern found but no live execution data for {symbol}"
                    )
                    continue

                # TODO: ADD HERE WHATSAPP NOTIFICATIONS with execution data
                
                # Place MT5 order (only if MT5 module is available)
                if mt5:
                    order_type = mt5.ORDER_TYPE_BUY if direction == TrendDirection.BULLISH else mt5.ORDER_TYPE_SELL
                    order_result = place_order(
                        symbol=symbol,
                        order_type=order_type,
                        price=execution.entry_price,
                        volume=execution.lot_size,
                        sl=execution.sl_price,
                        tp=execution.tp_price,
                        comment=f"Trenda signal",
                    )
                    
                    if order_result is None or (hasattr(order_result, 'retcode') and order_result.retcode != mt5.TRADE_RETCODE_DONE):
                        logger.error(
                            f"    ❌ MT5 order failed for {symbol}. Skipping signal storage."
                        )
                        continue
                    
                    logger.info(
                        f"    💰 MT5 ORDER PLACED: Ticket #{order_result.order} | "
                        f"{direction.value} {symbol} @ {execution.entry_price:.5f}"
                    )
                    
                    # Verify SL/TP consistency
                    is_consistent = verify_sl_tp_consistency(
                        ticket=order_result.order,
                        expected_sl=execution.sl_price,
                        expected_tp=execution.tp_price
                    )
                    
                    if not is_consistent:
                        logger.error(f"    ❌ Verification failed for {symbol}: SL/TP modified by broker. Trade CLOSED.")
                        continue
                else:
                    logger.warning(f"    ⚠️ MT5 not available. Skipping order placement for {symbol}.")
                    # Determine if we should skip storage or not. 
                    # If we can't trade, maybe we strictly skip? 
                    # For now, let's assume we skip storage if we can't place the trade, similar to the failure case.
                    logger.error("    ❌ MT5 module missing. Skipping signal storage.")
                    continue
                
                # Populate SignalData with live execution values
                signal.entry_price = execution.entry_price
                signal.sl_distance_atr = execution.sl_distance_atr
                signal.tp_distance_atr = execution.tp_distance_atr
                
                # NOW store signal with complete data
                entry_id = store_entry_signal_with_symbol(symbol, signal)
                if entry_id:
                    logger.info(
                        f"    ✅ Signal stored in DB (ID: {entry_id}, Score: {signal.total_score:.2f}) "
                    )
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


def _collect_trend_snapshot(
    timeframes: Sequence[str], symbol: str
) -> Mapping[str, Optional[TrendDirection]]:
    return {tf: get_trend_by_timeframe(symbol, tf) for tf in timeframes}


def _calculate_trend_alignment_strength(
    trend_snapshot: Mapping[str, Optional[TrendDirection]],
    direction: TrendDirection,
) -> int:
    """Count how many timeframes align with the given direction."""
    return sum(1 for tf_trend in trend_snapshot.values() if tf_trend == direction)


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



def _compute_sl_aoi_far_plus(
    direction: TrendDirection,
    entry_price: float,
    aoi_low: float,
    aoi_high: float,
    atr_1h: float,
) -> float:
    """
    Compute SL distance using SL_AOI_FAR_PLUS_0_25 model.
    
    SL = distance to far edge of AOI + SL_BUFFER_ATR
    
    For bullish: far edge = aoi_low
    For bearish: far edge = aoi_high
    """
    if atr_1h <= 0:
        return 0.0
    
    if direction == TrendDirection.BULLISH:
        far_edge_distance = entry_price - aoi_low
    else:
        far_edge_distance = aoi_high - entry_price
    
    return (far_edge_distance / atr_1h) + SL_BUFFER_ATR
