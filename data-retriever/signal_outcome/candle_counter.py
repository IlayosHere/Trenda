"""Utility for counting closed 1H candles between timestamps."""

from datetime import datetime, timedelta, timezone

from .constants import WEEKEND_DAYS


def count_closed_1h_candles_between(start: datetime, end: datetime) -> int:
    """
    Count closed 1H candles between start and end.

    Rules:
    - Count only CLOSED 1H candles
    - Exclude Saturdays and Sundays entirely (no trading)
    - Do NOT count the signal candle itself
    - Candle immediately after signal_time is candle #1

    Args:
        start: Signal time (candle containing this time is NOT counted)
        end: Current time (only count candles that closed before this)

    Returns:
        Number of closed 1H trading candles
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware datetimes")

    # Normalize to UTC
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    # Round start UP to next hour boundary (this is candle #1's CLOSE time)
    # A candle closing at 11:00 covers 10:00-11:00
    if start_utc.minute > 0 or start_utc.second > 0 or start_utc.microsecond > 0:
        first_close = start_utc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        # start is exactly on the hour - the candle closing at start is the signal candle
        # so first counted candle closes at start + 1 hour
        first_close = start_utc + timedelta(hours=1)

    # Round end DOWN to last completed hour (last closed candle's close time)
    last_close = end_utc.replace(minute=0, second=0, microsecond=0)

    if first_close > last_close:
        return 0

    # Count hours, excluding weekends
    count = 0
    current = first_close

    while current <= last_close:
        weekday = current.weekday()
        if weekday not in WEEKEND_DAYS:
            count += 1
        current += timedelta(hours=1)

    return count
