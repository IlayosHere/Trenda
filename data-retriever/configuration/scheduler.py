from __future__ import annotations

from jobs import evaluate_entry_signals, refresh_pre_close_data, run_aoi_batch, run_trend_batch

SCHEDULE_CONFIG = [
    {
        "id": "job_4_hour_trend",
        "name": "4H trend monitoring",
        "timeframes": ["4H"],
        "interval_minutes": 60,
        "job": run_trend_batch,
        "args": [["4H"]],
        "trading_hours_only": True,
    },
    {
        "id": "job_daily_trend",
        "name": "1D trend monitoring",
        "timeframes": ["1D"],
        "interval_minutes": 240,
        "job": run_trend_batch,
        "args": [["1D"]],
        "trading_hours_only": True,
    },
    {
        "id": "job_weekly_trend",
        "name": "1W trend monitoring",
        "timeframes": ["1W"],
        "interval_minutes": 1440,
        "job": run_trend_batch,
        "args": [["1W"]],
        "trading_hours_only": True,
    },
    {
        "id": "job_4_hour_aoi",
        "name": "4H AOI refresh",
        "timeframes": ["4H"],
        "interval_minutes": 240,
        "job": run_aoi_batch,
        "args": [["4H"]],
        "trading_hours_only": True,
    },
    {
        "id": "job_daily_aoi",
        "name": "1D AOI refresh",
        "timeframes": ["1D"],
        "interval_minutes": 1440,
        "job": run_aoi_batch,
        "args": [["1D"]],
        "trading_hours_only": True,
    },
    {
        "id": "job_pre_close_refresh",
        "name": "Pre-close refresh",
        "interval_minutes": 60,
        "offset_minutes": 55,
        "job": refresh_pre_close_data,
        "trading_hours_only": True,
    },
    {
        "id": "job_hourly_entry_signals",
        "name": "1H entry signal evaluation",
        "timeframes": ["1H"],
        "interval_minutes": 60,
        "offset_seconds": 15,
        "job": evaluate_entry_signals,
        "args": ["1H"],
        "trading_hours_only": True,
    },
]
