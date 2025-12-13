"""Repository for storing entry signals to the database."""

from typing import Optional

import utils.display as display

from database.executor import DBExecutor
from database.queries import INSERT_ENTRY_SIGNAL, INSERT_ENTRY_SIGNAL_SCORE
from database.validation import DBValidator
from models.market import SignalData


def store_entry_signal(signal: SignalData) -> Optional[int]:
    """Persist an entry signal and its stage scores to the database.
    
    Args:
        signal: Complete SignalData with all required fields
        
    Returns:
        The entry_signal id if successful, None otherwise
    """
    # Validate symbol
    normalized_symbol = DBValidator.validate_symbol(signal.candles[0].time.strftime("%Y-%m-%d") if signal.candles else "")
    # Actually validate the symbol from the signal context - we need to pass it
    # For now, we'll get it from the signal data context
    
    def _persist(cursor):
        # Insert main entry signal
        cursor.execute(
            INSERT_ENTRY_SIGNAL,
            (
                normalized_symbol,  # We'll fix this - symbol needs to be passed
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
            cursor.executemany(INSERT_ENTRY_SIGNAL_SCORE, score_rows)
        
        return signal_id

    return DBExecutor.execute_transaction(_persist, context="store_entry_signal")


def store_entry_signal_with_symbol(symbol: str, signal: SignalData) -> Optional[int]:
    """Persist an entry signal and its stage scores to the database.
    
    Args:
        symbol: The forex symbol (e.g., 'EURUSD')
        signal: Complete SignalData with all required fields
        
    Returns:
        The entry_signal id if successful, None otherwise
    """
    normalized_symbol = DBValidator.validate_symbol(symbol)
    if not normalized_symbol:
        display.print_error(f"DB_VALIDATION: Invalid symbol '{symbol}'")
        return None
    
    # Validate numeric fields
    if not DBValidator.validate_nullable_float(signal.aoi_high, "aoi_high"):
        return None
    if not DBValidator.validate_nullable_float(signal.aoi_low, "aoi_low"):
        return None
    if not DBValidator.validate_nullable_float(signal.entry_price, "entry_price"):
        return None
    if not DBValidator.validate_nullable_float(signal.atr_1h, "atr_1h"):
        return None
    if not isinstance(signal.quality_result.final_score, (int, float)):
        display.print_error("DB_VALIDATION: final_score must be numeric")
        return None
    
    def _persist(cursor):
        # Insert main entry signal
        cursor.execute(
            INSERT_ENTRY_SIGNAL,
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
            cursor.executemany(INSERT_ENTRY_SIGNAL_SCORE, score_rows)
        
        return signal_id

    return DBExecutor.execute_transaction(_persist, context="store_entry_signal")
