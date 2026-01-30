"""Repository for storing failed signals to the database."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Any
import json

from logger import get_logger

logger = get_logger(__name__)

from database.executor import DBExecutor
from database.queries import INSERT_FAILED_SIGNAL
from database.validation import DBValidator
from models import TrendDirection


def _to_python_type(value: Any) -> Any:
    """Convert numpy types to native Python types for database insertion."""
    if value is None:
        return None
    # Handle numpy types
    if hasattr(value, 'item'):
        return value.item()
    return value


@dataclass
class FailedSignalData:
    """Data for a failed signal detection."""
    symbol: str
    failed_signal_time: datetime
    failed_gate: str
    fail_reason: str
    
    # Optional fields (available depending on how far detection progressed)
    direction: Optional[TrendDirection] = None
    tradable_aois: Optional[List[dict]] = None  # List of {aoi_high, aoi_low, timeframe}
    reference_price: Optional[float] = None
    atr_1h: Optional[float] = None
    htf_score: Optional[float] = None
    obstacle_score: Optional[float] = None
    total_score: Optional[float] = None
    sl_model: Optional[str] = None
    htf_range_position_daily: Optional[float] = None
    htf_range_position_weekly: Optional[float] = None
    distance_to_next_htf_obstacle_atr: Optional[float] = None
    conflicted_tf: Optional[str] = None
    is_break_candle_last: Optional[bool] = None


def store_failed_signal(data: FailedSignalData) -> bool:
    """Persist a failed signal to the database.
    
    Args:
        data: FailedSignalData with failure context
        
    Returns:
        True if successful, False otherwise
    """
    normalized_symbol = DBValidator.validate_symbol(data.symbol)
    if not normalized_symbol:
        logger.error(f"DB_VALIDATION: Invalid symbol '{data.symbol}'")
        return False
    
    # Convert AOIs list to JSON string
    aois_json = None
    aoi_count = None
    if data.tradable_aois is not None:
        aois_json = json.dumps(data.tradable_aois)
        aoi_count = len(data.tradable_aois)
    
    # Get direction value if available
    direction_value = data.direction.value if data.direction else None
    
    def _persist(cursor):
        cursor.execute(
            INSERT_FAILED_SIGNAL,
            (
                normalized_symbol,
                data.failed_signal_time,
                direction_value,
                aois_json,
                aoi_count,
                _to_python_type(data.reference_price),
                _to_python_type(data.atr_1h),
                _to_python_type(data.htf_score),
                _to_python_type(data.obstacle_score),
                _to_python_type(data.total_score),
                data.sl_model,
                _to_python_type(data.htf_range_position_daily),
                _to_python_type(data.htf_range_position_weekly),
                _to_python_type(data.distance_to_next_htf_obstacle_atr),
                data.conflicted_tf,
                data.is_break_candle_last,
                data.failed_gate,
                data.fail_reason,
            ),
        )
        return True

    result = DBExecutor.execute_transaction(_persist, context="store_failed_signal")
    return result is True
