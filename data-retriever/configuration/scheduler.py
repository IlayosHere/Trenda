from __future__ import annotations

from entry.detector import run_1h_entry_scan_job
from jobs import refresh_pre_close_data

SCHEDULE_CONFIG = [
    {
        "id": "job_pre_close_refresh",
        "name": "Pre-close refresh",
        "interval_minutes": 1,
        "offset_minutes": 0,
        "job": refresh_pre_close_data,
        "trading_hours_only": True,
    },
    # {
    #     "id": "job_hourly_entry_signals",
    #     "name": "1H entry signal evaluation",
    #     "timeframes": ["1H"],
    #     "interval_minutes": 60,
    #     "offset_seconds": 30,
    #     "job": run_1h_entry_scan_job,
    #     "args": ["1H"],
    #     "trading_hours_only": True,
    # },
]
