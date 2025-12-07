from __future__ import annotations

from entry.detector import run_1h_entry_scan_job
from jobs import TIMEFRAME_JOB_RUNNERS

SCHEDULE_CONFIG = [
    {
        "id": "job_4h_timeframe_analysis",
        "name": "4H AOI and trend update",
        "interval_minutes": 60 * 4,
        "offset_seconds": 10,
        "job": TIMEFRAME_JOB_RUNNERS["4H"],
    },
    {
        "id": "job_1d_timeframe_analysis",
        "name": "1D AOI and trend update",
        "interval_minutes": 60 * 24,
        "offset_seconds": 15,
        "job": TIMEFRAME_JOB_RUNNERS["1D"],
    },
    {
        "id": "job_1w_timeframe_analysis",
        "name": "1W trend update",
        "interval_minutes": 60 * 24 * 7,
        "offset_seconds": 20,
        "job": TIMEFRAME_JOB_RUNNERS["1W"],
    },
    {
        "id": "job_hourly_entry_signals",
        "name": "1H entry signal evaluation",
        "timeframes": ["1H"],
        "interval_minutes": 60,
        "offset_seconds": 30,
        "job": run_1h_entry_scan_job,
        "args": ["1H"],
        "trading_hours_only": True,
    },
]
