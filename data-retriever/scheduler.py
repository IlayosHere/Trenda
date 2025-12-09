from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from apscheduler.schedulers.background import BackgroundScheduler

import utils.display as display
from configuration import SCHEDULE_CONFIG
from utils.trading_hours import describe_trading_window, is_within_trading_hours

# Create a single, global scheduler instance
scheduler = BackgroundScheduler(daemon=True, timezone="UTC")


def start_scheduler() -> None:
    display.print_status("Starting background scheduler...")
    display.print_status(f"Trading window (UTC): {describe_trading_window()}")

    for config in SCHEDULE_CONFIG:
        try:
            job_func, next_run_time = _prepare_job(config)
        except KeyError as err:
            display.print_error(f"Missing scheduler config key {err} in {config}")
            continue

        interval_minutes = config["interval_minutes"]
        job_name = config.get("name", config["id"])

        display.print_status(
            f"  -> Scheduling '{job_name}' every {interval_minutes} mins (next at {next_run_time.isoformat()})."
        )
        _add_job(scheduler, config, job_func, next_run_time)

    try:
        scheduler.start()
        display.print_status("✅ Scheduler is running in the background.")
    except Exception as e:
        display.print_error(f"Failed to start scheduler: {e}")


def _add_job(scheduler: BackgroundScheduler, config: Dict[str, Any], job: Any, next_run_time: datetime) -> None:
    scheduler.add_job(
        job,
        "interval",
        minutes=config["interval_minutes"],
        id=config["id"],
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60 * 5,  # Allow job to be 5 mins late
        next_run_time=next_run_time
    )


def _prepare_job(config: Dict[str, Any]):
    job = config["job"]
    interval_minutes = config["interval_minutes"]
    offset_minutes = config.get("offset_minutes", 0)
    offset_seconds = config.get("offset_seconds", 0)
    job_name = config.get("name", config["id"])
    trading_hours_only = config.get("trading_hours_only", False)

    args: List[Any] = list(config.get("args", []))
    if not args and config.get("timeframes"):
        args = list(config["timeframes"])

    kwargs = config.get("kwargs", {})

    wrapped_job = _wrap_with_trading_hours(job, job_name, trading_hours_only, args, kwargs)
    next_run_time = _compute_next_run_time(interval_minutes, offset_minutes, offset_seconds)
    return wrapped_job, next_run_time


def _wrap_with_trading_hours(job, job_name: str, trading_hours_only: bool, args: List[Any], kwargs: Dict[str, Any]):
    def _runner():
        if trading_hours_only and not is_within_trading_hours():
            display.print_status(
                f"⏩ Skipping '{job_name}': outside configured trading hours."
            )
            return
        try:
            job(*args, **kwargs)
        except Exception as e:
            display.print_error(f"Job '{job_name}' failed: {e}")

    return _runner


def _compute_next_run_time(interval_minutes: int, offset_minutes: int = 0, offset_seconds: int = 0) -> datetime:
    interval_seconds = interval_minutes * 60
    offset_total = offset_minutes * 60 + offset_seconds

    now = datetime.now(timezone.utc)
    now_seconds = int(now.timestamp())
    cycles = ((now_seconds - offset_total) // interval_seconds) + 1
    next_seconds = (cycles * interval_seconds) + offset_total
    return datetime.fromtimestamp(next_seconds, tz=timezone.utc)
