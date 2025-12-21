from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Iterable, Set

import utils.display as display

DEFAULT_TRADING_DAYS = "0-4"  # Monday=0, Sunday=6
DEFAULT_TRADING_HOURS = "4-15"  # 24/7 by default


def _parse_range_list(raw_value: str, max_value: int) -> Set[int]:
    """Parse comma-separated ranges like "0-4,6" into a set of ints."""

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

            if start > end:
                continue

            allowed.update(range(start, end + 1))
        else:
            try:
                allowed.add(int(piece))
            except ValueError:
                continue

    return {value for value in allowed if 0 <= value <= max_value}


def _load_trading_window() -> tuple[Set[int], Set[int]]:
    raw_days = os.getenv("TRADING_DAYS", DEFAULT_TRADING_DAYS)
    raw_hours = os.getenv("TRADING_HOURS_UTC", DEFAULT_TRADING_HOURS)

    days = _parse_range_list(raw_days, max_value=6)
    hours = _parse_range_list(raw_hours, max_value=23)

    if not days:
        display.print_error(
            "TRADING_DAYS is misconfigured; defaulting to Monday-Friday (0-4)."
        )
        days = _parse_range_list(DEFAULT_TRADING_DAYS, max_value=6)

    if not hours:
        display.print_error(
            "TRADING_HOURS_UTC is misconfigured; defaulting to 24/7 (0-23)."
        )
        hours = _parse_range_list(DEFAULT_TRADING_HOURS, max_value=23)

    return days, hours


TRADING_DAYS, TRADING_HOURS = _load_trading_window()


def is_market_open(now: datetime | None = None) -> bool:
    """
    Return True if the forex market is open.
    
    Forex market hours: Sunday 22:00 UTC to Friday 22:00 UTC.
    - Sunday (weekday=6): open from 22:00 UTC onwards
    - Monday-Thursday (weekday=0-3): open all day
    - Friday (weekday=4): open until 22:00 UTC
    - Saturday (weekday=5): closed all day
    """
    current = now or datetime.now(timezone.utc)
    weekday = current.weekday()
    hour = current.hour
    
    if weekday == 5:  # Saturday - closed
        return False
    if weekday == 6:  # Sunday - open from 22:00 UTC
        return hour >= 22
    if weekday == 4:  # Friday - open until 22:00 UTC
        return hour < 22
    # Monday-Thursday - open all day
    return True


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
