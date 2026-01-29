from __future__ import annotations

from typing import Callable


def _get_job_func(module_path: str, func_name: str) -> Callable:
    """Lazily import and return a job function to avoid circular imports.
    
    This function is called at runtime when the scheduler needs to execute a job,
    not at module load time when the config is first imported.
    """
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


# Store job references as (module_path, function_name) tuples
# These are resolved lazily at runtime to avoid circular imports
_JOB_REFS = {
    "run_timeframe_job": ("jobs", "run_timeframe_job"),
    "run_1h_entry_scan_job": ("entry.detector", "run_1h_entry_scan_job"),
    "run_signal_outcome_processor": ("signal_outcome.outcome_processor", "run_signal_outcome_processor"),
}


def get_job(job_name: str) -> Callable:
    """Get a job function by its name. Resolves the import lazily."""
    module_path, func_name = _JOB_REFS[job_name]
    return _get_job_func(module_path, func_name)


SCHEDULE_CONFIG = [
    {
        "timeframe": "4H",
        "id": "job_4h_timeframe_analysis",
        "name": "4H AOI and trend update",
        "interval_minutes": 60 * 4,
        "offset_seconds": 10,
        "job_name": "run_timeframe_job",  # Changed from "job" to "job_name"
        "args": ["4H"],
        "kwargs": {"include_aoi": True},
        "market_hours_only": True,
    },
    {
        "timeframe": "1D",
        "id": "job_1d_timeframe_analysis",
        "name": "1D AOI and trend update",
        "interval_minutes": 60 * 24,
        "offset_seconds": 30,
        "job_name": "run_timeframe_job",
        "args": ["1D"],
        "kwargs": {"include_aoi": True},
        "market_hours_only": True,
    },
    {
        "timeframe": "1W",
        "id": "job_1w_timeframe_analysis",
        "name": "1W trend update",
        "interval_minutes": 60 * 24 * 7,
        "offset_seconds": 50,
        "job_name": "run_timeframe_job",
        "args": ["1W"],
        "kwargs": {"include_aoi": False},
    },
    {
        "timeframe": "1H",
        "id": "job_hourly_entry_signals",
        "name": "1H entry signal evaluation",
        "timeframes": ["1H"],
        "interval_minutes": 60,
        "offset_seconds": 80,
        "job_name": "run_1h_entry_scan_job",
        "args": ["1H"],
        "trading_hours_only": True,
    },
    {
        "timeframe": "1H",
        "id": "job_signal_outcome",
        "name": "Signal outcome computation",
        "interval_minutes": 60,
        "offset_seconds": 300,  # 5 min delay after candle close
        "job_name": "run_signal_outcome_processor",
        "args": [],
        "trading_hours_only": False,  # Run even outside trading hours to catch up
    },
]

