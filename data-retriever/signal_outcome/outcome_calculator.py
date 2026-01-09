"""Outcome calculation logic for signal performance analysis."""

import pandas as pd

from models import TrendDirection

from .constants import (
    OUTCOME_WINDOW_BARS,
    FirstExtreme,
    FirstExtremeType,
    ExitReason,
)
from .models import OutcomeData, PendingSignal


def compute_outcome(signal: PendingSignal, candles: pd.DataFrame) -> OutcomeData:
    """
    Compute outcome metrics from post-signal candles.
    
    All outputs are normalized in ATR units relative to entry_price.
    
    Args:
        signal: The signal being processed (contains direction, entry_price, atr_1h, sl_distance_atr)
        candles: DataFrame with OUTCOME_WINDOW_BARS candles after signal
        
    Returns:
        OutcomeData containing core outcome data with exit tracking
    """
    direction = TrendDirection.from_raw(signal.direction)
    is_bullish = direction == TrendDirection.BULLISH
    entry_price = signal.entry_price
    atr = signal.atr_1h
    
    # Handle legacy signals without sl_distance_atr by computing from AOI bounds
    sl_distance_atr = signal.sl_distance_atr
    if sl_distance_atr is None:
        # Compute from AOI bounds (same logic as live_execution.py)
        if is_bullish:
            far_edge_distance = entry_price - signal.aoi_low
        else:
            far_edge_distance = signal.aoi_high - entry_price
        sl_distance_atr = (far_edge_distance / atr) + 0.25  # SL_BUFFER_ATR = 0.25
    
    # Compute MFE and MAE
    mfe_atr, bars_to_mfe = _compute_mfe(candles, entry_price, atr, is_bullish)
    mae_atr, bars_to_mae = _compute_mae(candles, entry_price, atr, is_bullish)
    
    # Determine which extreme was reached first
    first_extreme = _determine_first_extreme(
        mfe_atr, mae_atr, bars_to_mfe, bars_to_mae
    )
    
    # Compute checkpoint returns (48, 72, 96)
    return_after_48 = _compute_return_at_bar(candles, 48, entry_price, atr, is_bullish)
    return_after_72 = _compute_return_at_bar(candles, 72, entry_price, atr, is_bullish)
    return_after_96 = _compute_return_at_bar(candles, 96, entry_price, atr, is_bullish)
    
    # Compute exit (SL/TP/TIMEOUT)
    exit_reason, bars_to_exit = _compute_exit(
        candles=candles,
        entry_price=entry_price,
        atr=atr,
        sl_distance_atr=sl_distance_atr,
        is_bullish=is_bullish,
    )
    
    return OutcomeData(
        window_bars=OUTCOME_WINDOW_BARS,
        mfe_atr=mfe_atr,
        mae_atr=mae_atr,
        bars_to_mfe=bars_to_mfe,
        bars_to_mae=bars_to_mae,
        first_extreme=first_extreme,
        return_after_48=return_after_48,
        return_after_72=return_after_72,
        return_after_96=return_after_96,
        exit_reason=exit_reason,
        bars_to_exit=bars_to_exit,
    )


def _compute_exit(
    candles: pd.DataFrame,
    entry_price: float,
    atr: float,
    sl_distance_atr: float,
    is_bullish: bool,
) -> tuple[str, int | None]:
    """
    Determine exit reason and bar.
    
    Uses sl_distance_atr for SL detection and 2.0 * sl_distance_atr for TP.
    
    Returns:
        (exit_reason, bars_to_exit) - 'SL', 'TP', or 'TIMEOUT' and bar number
    """
    sl_distance_price = sl_distance_atr * atr
    tp_distance_price = sl_distance_atr * 2.0 * atr  # RR 2.0
    
    bars_to_sl = None
    bars_to_tp = None
    
    for i, (_, candle) in enumerate(candles.iterrows(), start=1):
        if is_bullish:
            # SL hit if low goes below entry - SL
            if bars_to_sl is None and candle["low"] <= entry_price - sl_distance_price:
                bars_to_sl = i
            # TP hit if high goes above entry + TP
            if bars_to_tp is None and candle["high"] >= entry_price + tp_distance_price:
                bars_to_tp = i
        else:
            # SL hit if high goes above entry + SL
            if bars_to_sl is None and candle["high"] >= entry_price + sl_distance_price:
                bars_to_sl = i
            # TP hit if low goes below entry - TP
            if bars_to_tp is None and candle["low"] <= entry_price - tp_distance_price:
                bars_to_tp = i
        
        # Early exit if both found
        if bars_to_sl is not None and bars_to_tp is not None:
            break
    
    # Determine exit reason
    if bars_to_sl is not None and bars_to_tp is not None:
        # Both hit - which first?
        if bars_to_sl <= bars_to_tp:
            return ExitReason.SL.value, bars_to_sl
        else:
            return ExitReason.TP.value, bars_to_tp
    elif bars_to_sl is not None:
        return ExitReason.SL.value, bars_to_sl
    elif bars_to_tp is not None:
        return ExitReason.TP.value, bars_to_tp
    else:
        return ExitReason.TIMEOUT.value, None


def _compute_mfe(
    candles: pd.DataFrame, entry_price: float, atr: float, is_bullish: bool
) -> tuple[float, int]:
    """
    Compute Maximum Favorable Excursion.
    
    Returns:
        (mfe_atr, bars_to_mfe) - MFE in ATR units and 1-based bar index
    """
    max_favorable = 0.0
    max_bar = OUTCOME_WINDOW_BARS  # Default if never favorable

    for i, (_, candle) in enumerate(candles.iterrows(), start=1):
        if is_bullish:
            favorable_move = candle["high"] - entry_price
        else:
            favorable_move = entry_price - candle["low"]
        
        favorable_atr = favorable_move / atr if atr > 0 else 0.0
        
        if favorable_atr > max_favorable:
            max_favorable = favorable_atr
            max_bar = i
    
    return max_favorable, max_bar


def _compute_mae(
    candles: pd.DataFrame, entry_price: float, atr: float, is_bullish: bool
) -> tuple[float, int]:
    """
    Compute Maximum Adverse Excursion.
    
    Returns:
        (mae_atr, bars_to_mae) - MAE in ATR units (≤0) and 1-based bar index
    """
    min_adverse = 0.0
    min_bar = OUTCOME_WINDOW_BARS  # Default if never adverse

    for i, (_, candle) in enumerate(candles.iterrows(), start=1):
        if is_bullish:
            adverse_move = candle["low"] - entry_price
        else:
            adverse_move = entry_price - candle["high"]
        
        adverse_atr = adverse_move / atr if atr > 0 else 0.0
        
        if adverse_atr < min_adverse:
            min_adverse = adverse_atr
            min_bar = i
    
    return min_adverse, min_bar


def _determine_first_extreme(
    mfe_atr: float, mae_atr: float, bars_to_mfe: int, bars_to_mae: int
) -> FirstExtremeType:
    """
    Determine which extreme (MFE or MAE) was reached first.
    
    Returns one of the FirstExtreme enum values.
    """
    has_mfe = mfe_atr > 0
    has_mae = mae_atr < 0
    
    if has_mfe and has_mae:
        if bars_to_mfe < bars_to_mae:
            return FirstExtreme.MFE_FIRST.value
        return FirstExtreme.MAE_FIRST.value
    elif has_mfe:
        return FirstExtreme.ONLY_MFE.value
    elif has_mae:
        return FirstExtreme.ONLY_MAE.value
    else:
        return FirstExtreme.NONE.value


def _compute_return_at_bar(
    candles: pd.DataFrame, bar_number: int, entry_price: float, atr: float, is_bullish: bool
) -> float | None:
    """
    Compute return at a specific bar number (1-based).
    
    Args:
        candles: DataFrame with candles
        bar_number: 1-based bar index
        entry_price: Entry price of the signal
        atr: ATR for normalization
        is_bullish: True if bullish direction
        
    Returns:
        Return in ATR units, or None if bar doesn't exist
    """
    if bar_number > len(candles):
        return None
    
    # bar_number is 1-based, DataFrame index is 0-based
    candle = candles.iloc[bar_number - 1]
    close_price = candle["close"]
    
    if is_bullish:
        return_move = close_price - entry_price
    else:
        return_move = entry_price - close_price
    
    return return_move / atr if atr > 0 else 0.0
