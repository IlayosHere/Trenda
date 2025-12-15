from __future__ import annotations

from entry.detector import run_1h_entry_scan_job
from signal_outcome.outcome_processor import run_signal_outcome_processor
from utils.bot_check import run_bot_check
from jobs import run_timeframe_job

SCHEDULE_CONFIG = [
    {
        "timeframe": "4H",
        "id": "job_4h_timeframe_analysis",
        "name": "4H AOI and trend update",
        "interval_minutes": 60 * 4,
        "offset_seconds": 10,
        "job": run_timeframe_job,
        "args": ["4H"],
        "kwargs": {"include_aoi": True},
    },
    {
        "timeframe": "1D",
        "id": "job_1d_timeframe_analysis",
        "name": "1D AOI and trend update",
        "interval_minutes": 60 * 24,
        "offset_seconds": 15,
        "job": run_timeframe_job,
        "args": ["1D"],
        "kwargs": {"include_aoi": True},
    },
    {
        "timeframe": "1W",
        "id": "job_1w_timeframe_analysis",
        "name": "1W trend update",
        "interval_minutes": 60 * 24 * 7,
        "offset_seconds": 20,
        "job": run_timeframe_job,
        "args": ["1W"],
        "kwargs": {"include_aoi": False},
    },
    {
        "timeframe": "1H",
        "id": "job_hourly_entry_signals",
        "name": "1H entry signal evaluation",
        "timeframes": ["1H"],
        "interval_minutes": 60,
        "offset_seconds": 30,
        "job": run_1h_entry_scan_job,
        "args": ["1H"],
        "trading_hours_only": True,
    },
    {
        "timeframe": "1H",
        "id": "job_signal_outcome",
        "name": "Signal outcome computation",
        "interval_minutes": 60,
        "offset_seconds": 120,  # 2 min delay after candle close
        "job": run_signal_outcome_processor,
        "args": [],
        "trading_hours_only": False,  # Run even outside trading hours to catch up
    },
]

