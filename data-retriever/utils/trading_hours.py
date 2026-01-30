from __future__ import annotations
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
import os
from typing import Iterable, Set

from logger import get_logger

logger = get_logger(__name__)

DEFAULT_TRADING_DAYS = "0-5"  # Monday=0, Sunday=6
# Trading window: 22:00-23:00 UTC and 00:00-12:00 UTC (wraps around midnight)
DEFAULT_TRADING_HOURS = "21-23,0-11"



def _parse_range_list(raw_value: str, max_value: int) -> Set[int]:
    """Parse comma-separated ranges like "0-4,6" or "22-12" into a set of ints.
    
    Supports wrap-around ranges (e.g., "22-12" for hours means 22,23,0,1,...,12).
    """

    allowed: Set[int] = set()

    for part in raw_value.split(","):
        piece = part.strip()
        if not piece:
            continue

        if "-" in piece:
            start_str, end_str = piece.split("-", 1)
            try:
                start = int(start_str)
                end = int(end_str)
            except ValueError:
                continue

            if start <= end:
                # Normal range (e.g., 0-12)
                allowed.update(range(start, end + 1))
            else:
                # Wrap-around range (e.g., 22-12 means 22,23,0,1,...,12)
                # From start to max_value, then from 0 to end
                allowed.update(range(start, max_value + 1))
                allowed.update(range(0, end + 1))
        else:
            try:
                allowed.add(int(piece))
            except ValueError:
                continue

    return {value for value in allowed if 0 <= value <= max_value}


def _load_trading_window() -> tuple[Set[int], Set[int]]:
    raw_days = os.getenv("TRADING_DAYS", DEFAULT_TRADING_DAYS)
    raw_hours = os.getenv("TRADING_HOURS", DEFAULT_TRADING_HOURS)

    days = _parse_range_list(raw_days, max_value=6)
    hours = _parse_range_list(raw_hours, max_value=23)

    if not days:
        logger.error(
            "TRADING_DAYS is misconfigured; defaulting to Monday-Friday (0-4)."
        )
        days = _parse_range_list(DEFAULT_TRADING_DAYS, max_value=6)

    if not hours:
        logger.error(
            "TRADING_HOURS_UTC is misconfigured; defaulting to 24/7 (0-23)."
        )
        hours = _parse_range_list(DEFAULT_TRADING_HOURS, max_value=23)

    return days, hours


TRADING_DAYS, TRADING_HOURS = _load_trading_window()


def is_market_open(now: datetime | None = None) -> bool:
    """
    Return True if the forex market is open.

    Forex market hours (NY time):
    - Sunday: open from 17:00
    - Monday–Thursday: open all day
    - Friday: open until 17:00
    - Saturday: closed
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    ny_time = now.astimezone(ZoneInfo("America/New_York"))

    weekday = ny_time.weekday()
    hour = ny_time.hour

    if weekday == 5:      # Saturday
        return False
    if weekday == 6:      # Sunday
        return hour >= 17
    if weekday == 4:      # Friday
        return hour < 17

    return True            # Monday–Thursday


def is_within_trading_hours(now: datetime | None = None) -> bool:
    """Return True when the provided UTC datetime falls inside the trading window."""

    current = now or datetime.now(timezone.utc)
    return current.weekday() in TRADING_DAYS and current.hour in TRADING_HOURS


def describe_trading_window() -> str:
    """Human-friendly description of the configured trading window."""

    def _collapse(values: Iterable[int]) -> str:
        sorted_vals = sorted(values)
        ranges = []
        start = prev = None

        for value in sorted_vals:
            if start is None:
                start = prev = value
                continue

            if value == prev + 1:
                prev = value
                continue

            ranges.append((start, prev))
            start = prev = value

        if start is not None:
            ranges.append((start, prev))

        return ",".join(
            f"{s}-{e}" if s != e else f"{s}" for s, e in ranges
        )

    day_range = _collapse(TRADING_DAYS)
    hour_range = _collapse(TRADING_HOURS)
    return f"Days {day_range}, Hours(UTC) {hour_range}"
