"""MT5 broker configuration."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# MT5 broker timezone (for DST-aware offset calculation)
# Default: Europe/Athens (EET/EEST) - standard for most forex brokers
# Set to Asia/Jerusalem if your broker uses Israel time
MT5_BROKER_TIMEZONE: str = os.getenv("MT5_BROKER_TIMEZONE", "Europe/Athens")

# Legacy static offset (kept for backward compatibility, but prefer get_broker_utc_offset())
MT5_BROKER_UTC_OFFSET: int = int(os.getenv("MT5_BROKER_UTC_OFFSET", "2"))


def get_broker_utc_offset(timestamp: datetime | None = None) -> int:
    """Get broker UTC offset for a given timestamp (handles DST).
    
    Args:
        timestamp: The timestamp to check (defaults to current time if None)
        
    Returns:
        UTC offset in hours (e.g., 2 for winter EET, 3 for summer EEST)
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif timestamp.tzinfo is None:
        # Assume UTC if no timezone provided
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    try:
        broker_tz = ZoneInfo(MT5_BROKER_TIMEZONE)
        local_time = timestamp.astimezone(broker_tz)
        offset_seconds = local_time.utcoffset().total_seconds()
        return int(offset_seconds / 3600)
    except Exception:
        # Fallback to static offset if timezone lookup fails
        return MT5_BROKER_UTC_OFFSET
