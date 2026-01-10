"""Repository for storing entry signals to the database."""

from typing import Optional

from logger import get_logger

logger = get_logger(__name__)

from database.executor import DBExecutor
from database.queries import INSERT_ENTRY_SIGNAL
from database.validation import DBValidator
from models.market import SignalData


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


    try:
        trend_values = (
            required_trend(trend_snapshot, "4H"),
            required_trend(trend_snapshot, "1D"),
            required_trend(trend_snapshot, "1W"),
        )
    except (TypeError, ValueError) as exc:
        logger.error(f"DB_VALIDATION: invalid trend snapshot - {exc}")
        return None

    def _validate_candle_value(value: Any, field: str) -> Optional[float]:
        if not isinstance(value, (int, float)):
            logger.error(f"DB_VALIDATION: candle {field} must be numeric")
            return None
        return float(value)

    def _persist(cursor):
        cursor.execute(
            INSERT_ENTRY_SIGNAL,
            (
                normalized_symbol,
                signal.signal_time,
                signal.direction.value,
                signal.aoi_timeframe,
                signal.aoi_low,
                signal.aoi_high,
                signal.entry_price,
                signal.atr_1h,
                signal.htf_score,
                signal.obstacle_score,
                signal.total_score,
                signal.sl_model,
                signal.sl_distance_atr,
                signal.tp_distance_atr,
                signal.rr_multiple,
                signal.is_break_candle_last,
                signal.htf_range_position_daily,
                signal.htf_range_position_weekly,
                signal.distance_to_next_htf_obstacle_atr,
                signal.conflicted_tf,
            ),
        )
        signal_id = cursor.fetchone()[0]
        return signal_id

    return DBExecutor.execute_transaction(_persist, context="store_entry_signal")
