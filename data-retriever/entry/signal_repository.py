"""Repository for storing entry signals to the database."""

from typing import Any, Optional

from logger import get_logger

logger = get_logger(__name__)

from database.executor import DBExecutor
from database.queries import INSERT_ENTRY_SIGNAL
from database.validation import DBValidator
from models.market import SignalData


def _to_python_type(value: Any) -> Any:
    """Convert numpy types to native Python types for database insertion."""
    if value is None:
        return None
    # Handle numpy types
    if hasattr(value, 'item'):
        return value.item()
    return value


def store_entry_signal_with_symbol(symbol: str, signal: SignalData) -> Optional[int]:
    """Persist an entry signal to the database.
    
    Signal is stored with complete execution data (entry_price, sl_distance_atr, tp_distance_atr).
    
    Args:
        symbol: The forex symbol (e.g., 'EURUSD')
        signal: Complete SignalData with all required fields
        
    Returns:
        The entry_signal id if successful, None otherwise
    """
    normalized_symbol = DBValidator.validate_symbol(symbol)
    if not normalized_symbol:
        logger.error(f"DB_VALIDATION: Invalid symbol '{symbol}'")
        return None    
    # Validate required numeric fields
    if not DBValidator.validate_nullable_float(signal.aoi_high, "aoi_high"):
        return None
    if not DBValidator.validate_nullable_float(signal.aoi_low, "aoi_low"):
        return None
    if not DBValidator.validate_nullable_float(signal.atr_1h, "atr_1h"):
        return None
    
    def _persist(cursor):
        cursor.execute(
            INSERT_ENTRY_SIGNAL,
            (
                normalized_symbol,
                signal.signal_time,
                signal.direction.value,
                signal.aoi_timeframe,
                _to_python_type(signal.aoi_low),
                _to_python_type(signal.aoi_high),
                _to_python_type(signal.entry_price),
                _to_python_type(signal.atr_1h),
                _to_python_type(signal.htf_score),
                _to_python_type(signal.obstacle_score),
                _to_python_type(signal.total_score),
                signal.sl_model,
                _to_python_type(signal.sl_distance_atr),
                _to_python_type(signal.tp_distance_atr),
                _to_python_type(signal.rr_multiple),
                _to_python_type(signal.actual_rr),
                _to_python_type(signal.price_drift),
                signal.is_break_candle_last,
                _to_python_type(signal.htf_range_position_daily),
                _to_python_type(signal.htf_range_position_weekly),
                _to_python_type(signal.distance_to_next_htf_obstacle_atr),
                signal.conflicted_tf,
            ),
        )
        signal_id = cursor.fetchone()[0]
        return signal_id

    return DBExecutor.execute_transaction(_persist, context="store_entry_signal")
