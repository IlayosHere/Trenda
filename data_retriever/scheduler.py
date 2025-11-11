"""Background scheduler orchestration for recurring analyses."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from typing import Callable, Dict, Iterable

from apscheduler.schedulers.background import BackgroundScheduler

from data_retriever.configuration import SCHEDULE_CONFIG
from data_retriever.utils import display

# Create a single, global scheduler instance
scheduler = BackgroundScheduler(daemon=True, timezone="UTC")


def start_scheduler() -> None:
    display.print_status("Starting background scheduler...")

    # Add a job for each timeframe in the config
    for job_name, config in SCHEDULE_CONFIG.items():
        timeframes: Iterable[str] = config["timeframe"]
        interval_minutes: int = config["interval_minutes"]
        job = _resolve_callable(config["callable"])

        for timeframe in timeframes:
            display.print_status(
                f"  -> Scheduling job for '{timeframe}': running every {interval_minutes} mins"
            )
            add_job(job_name, timeframe, interval_minutes, job)

    try:
        scheduler.start()
        display.print_status("✅ Scheduler is running in the background.")
    except Exception as exc:  # pragma: no cover - defensive logging
        display.print_error(f"Failed to start scheduler: {exc}")


def add_job(job_name: str, timeframe: str, interval_minutes: int, job: Callable[[str], None]) -> None:
    job_id = f"{job_name}:{timeframe}"
    scheduler.add_job(
        job,
        "interval",
        minutes=interval_minutes,
        args=(timeframe,),
        id=job_id,
        replace_existing=True,
        misfire_grace_time=60 * 5,
        next_run_time=datetime.now(timezone.utc),
    )


_CALLABLE_CACHE: Dict[str, Callable[[str], None]] = {}


def _resolve_callable(path: str) -> Callable[[str], None]:
    if path not in _CALLABLE_CACHE:
        module_path, func_name = path.rsplit(".", 1)
        try:
            module = import_module(module_path)
            callable_obj = getattr(module, func_name)
        except (ImportError, AttributeError) as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Unable to resolve scheduler callable '{path}': {exc}") from exc

        _CALLABLE_CACHE[path] = callable_obj
    return _CALLABLE_CACHE[path]


__all__ = ["scheduler", "start_scheduler", "add_job"]
