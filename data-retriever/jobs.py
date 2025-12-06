from __future__ import annotations

from typing import Iterable

from aoi import analyze_aoi_by_timeframe
import utils.display as display
from trend.workflow import analyze_trend_by_timeframe

PRE_CLOSE_TRENDS = ["4H", "1D", "1W"]
PRE_CLOSE_AOIS = ["4H", "1D"]

def run_trend_batch(timeframes: Iterable[str]) -> None:
    for timeframe in timeframes:
        analyze_trend_by_timeframe(timeframe)

def run_aoi_batch(timeframes: Iterable[str]) -> None:
    for timeframe in timeframes:
        analyze_aoi_by_timeframe(timeframe)

def refresh_pre_close_data() -> None:
    display.print_status("\n--- 🔁 Pre-close refresh for hourly entry checks ---")
    display.print_status(
        "  -> Updating trends for aligned timeframes: " + ", ".join(PRE_CLOSE_TRENDS)
    )
    run_trend_batch(PRE_CLOSE_TRENDS)

    display.print_status("  -> Refreshing AOIs ahead of the close: " + ", ".join(PRE_CLOSE_AOIS))
    run_aoi_batch(PRE_CLOSE_AOIS)