"""Declarative schedule configuration for background jobs."""

from __future__ import annotations

from typing import Dict


ScheduleConfig = Dict[str, object]


SCHEDULE_CONFIG: Dict[str, ScheduleConfig] = {
    "job_hourly_aoi": {
        "timeframe": ("4H",),
        "interval_minutes": 240,
        "callable": "data_retriever.analyzers.analyze_aoi_by_timeframe",
    },
    "job_hourly_trend": {
        "timeframe": ("1H",),
        "interval_minutes": 60,
        "callable": "data_retriever.analyzers.analyze_by_timeframe",
    },
    "job_4_hour_trend": {
        "timeframe": ("4H",),
        "interval_minutes": 240,
        "callable": "data_retriever.analyzers.analyze_by_timeframe",
    },
    "job_daily_trend": {
        "timeframe": ("1D",),
        "interval_minutes": 1440,
        "callable": "data_retriever.analyzers.analyze_by_timeframe",
    },
}

__all__ = ["SCHEDULE_CONFIG", "ScheduleConfig"]
