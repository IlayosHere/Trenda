"""Outcome calculation logic for signal performance analysis."""

import pandas as pd

from models import TrendDirection

from .constants import (
    CHECKPOINT_BARS,
    OUTCOME_WINDOW_BARS,
    FirstExtreme,
    FirstExtremeType,
)
from .models import OutcomeData, OutcomeWithCheckpoints, CheckpointReturn, PendingSignal
from .sl_tp_detector import compute_sl_tp_hits


def compute_outcome(signal: PendingSignal, candles: pd.DataFrame) -> OutcomeWithCheckpoints:
    """
    Compute outcome metrics from post-signal candles.
    
    All outputs are normalized in ATR units relative to entry_price.
    
    Args:
        signal: The signal being processed (contains direction, entry_price, atr_1h)
        candles: DataFrame with OUTCOME_WINDOW_BARS candles after signal
        
    Returns:
        OutcomeWithCheckpoints containing core outcome data and list of checkpoint returns
    """
    direction = TrendDirection.from_raw(signal.direction)
    is_bullish = direction == TrendDirection.BULLISH
    entry_price = signal.entry_price
    atr = signal.atr_1h
    
    # Compute MFE and MAE
    mfe_atr, bars_to_mfe = _compute_mfe(candles, entry_price, atr, is_bullish)
    mae_atr, bars_to_mae = _compute_mae(candles, entry_price, atr, is_bullish)
    
    # Determine which extreme was reached first
    first_extreme = _determine_first_extreme(
        mfe_atr, mae_atr, bars_to_mfe, bars_to_mae
    )
    
    # Compute checkpoint returns as list
    checkpoint_returns = _compute_checkpoint_returns_list(
        candles, entry_price, atr, is_bullish
    )
    
    # Compute SL/TP hits and R:R outcome
    sl_tp_hits = compute_sl_tp_hits(
        candles=candles,
        direction=direction,
        entry_price=entry_price,
        aoi_effective_sl_distance_price=signal.aoi_effective_sl_distance_price,
    )
    
    outcome = OutcomeData(
        window_bars=OUTCOME_WINDOW_BARS,
        mfe_atr=mfe_atr,
        mae_atr=mae_atr,
        bars_to_mfe=bars_to_mfe,
        bars_to_mae=bars_to_mae,
        first_extreme=first_extreme,
        # SL/TP hits
        bars_to_aoi_sl_hit=sl_tp_hits.bars_to_aoi_sl_hit,
        bars_to_r_1=sl_tp_hits.bars_to_r_1,
        bars_to_r_1_5=sl_tp_hits.bars_to_r_1_5,
        bars_to_r_2=sl_tp_hits.bars_to_r_2,
        aoi_rr_outcome=sl_tp_hits.aoi_rr_outcome,
    )
    
    return OutcomeWithCheckpoints(
        outcome=outcome,
        checkpoint_returns=checkpoint_returns,
    )


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


def _compute_checkpoint_returns_list(
    candles: pd.DataFrame, entry_price: float, atr: float, is_bullish: bool
) -> list[CheckpointReturn]:
    """
    Compute returns at all checkpoint bars.
    
    Returns:
        List of CheckpointReturn for each checkpoint that has data
    """
    returns = []
    
    for checkpoint in CHECKPOINT_BARS:
        return_atr = _compute_return_at_bar(
            candles, checkpoint, entry_price, atr, is_bullish
        )
        if return_atr is not None:
            returns.append(CheckpointReturn(
                bars_after=checkpoint,
                return_atr=return_atr,
            ))
    
    return returns


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
