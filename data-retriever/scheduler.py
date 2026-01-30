from __future__ import annotations

import tempfile
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from configuration.forex_config import TIMEFRAMES
from apscheduler.schedulers.background import BackgroundScheduler
from externals.data_fetcher import fetch_data
from logger import get_logger
from configuration import SCHEDULE_CONFIG
from configuration.scheduler_config import get_job
from utils.trading_hours import describe_trading_window, is_market_open, is_within_trading_hours
from notifications import notify

# Create a single, global scheduler instance
scheduler = BackgroundScheduler(daemon=True, timezone="UTC")

logger = get_logger(__name__)

STUB_FOREX_SYMBOL = "EURUSD"
HEARTBEAT_FILE = os.path.join(tempfile.gettempdir(), "trenda_healthy")

def _heartbeat():
    """Touch a file to indicate the scheduler is alive."""
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except Exception as e:
        logger.error(f"Heartbeat failed: {e}")

def run_startup_data_refresh() -> None:
    """Run all trend/AOI jobs at startup based on last closed candle."""
    logger.info("\n--- 🚀 Running startup data refresh ---")

    for config in SCHEDULE_CONFIG:
        timeframe = config.get("timeframe")
        if not timeframe or "job_name" not in config:
            continue
        # Skip non-timeframe jobs (entry signal, outcome jobs use 1H)
        if timeframe == "1H":
            continue

        display_name = config.get("name", config["id"])
        job = get_job(config["job_name"])
        args = list(config.get("args", []))
        kwargs = config.get("kwargs", {})

        logger.info(f"  -> Running startup job: {display_name}")
        try:
            job(*args, **kwargs)
        except Exception as e:
            logger.error(f"Startup job '{display_name}' failed: {e}")

    logger.info("--- ✅ Startup data refresh complete ---\n")


def start_scheduler() -> None:
    logger.info("Starting background scheduler...")
    logger.info(f"Trading window (UTC): {describe_trading_window()}")

    # Schedule Heartbeat
    scheduler.add_job(_heartbeat, "interval", hours=1, id="heartbeat", replace_existing=True)

    for config in SCHEDULE_CONFIG:
        try:
            job_func, next_run_time = _prepare_job(config)
        except KeyError as err:
            logger.error(f"Missing scheduler config key {err} in {config}")
            continue

        interval_minutes = config["interval_minutes"]
        job_name = config.get("name", config["id"])

        logger.info(
            f"  -> Scheduling '{job_name}' every {interval_minutes} mins (next at {next_run_time.isoformat()})."
        )
        _add_job(scheduler, config, job_func, next_run_time)

    try:
        scheduler.start()
        logger.info("✅ Scheduler is running in the background.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


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
    job = get_job(config["job_name"])
    interval_minutes = config["interval_minutes"]
    offset_seconds = config.get("offset_seconds", 0)
    job_name = config.get("name", config["id"])
    trading_hours_only = config.get("trading_hours_only", False)
    market_hours_only = config.get("market_hours_only", False)

    args: List[Any] = list(config.get("args", []))
    if not args and config.get("timeframes"):
        args = list(config["timeframes"])

    kwargs = config.get("kwargs", {})

    wrapped_job = _wrap_with_trading_hours(job, job_name, trading_hours_only, market_hours_only, args, kwargs)
    next_run_time = compute_first_run_time(config.get("timeframe"), interval_minutes, offset_seconds)
    return wrapped_job, next_run_time


def _wrap_with_trading_hours(job, job_name: str, trading_hours_only: bool, market_hours_only: bool, args: List[Any], kwargs: Dict[str, Any]):
    def _runner():
        # Check trading hours (specific hour-by-hour window)
        if trading_hours_only and not is_within_trading_hours():
            logger.info(
                f"⏩ Skipping '{job_name}': outside configured trading hours."
            )
            return
        # Check market hours (Sunday 22:00 UTC to Friday 22:00 UTC)
        if market_hours_only and not is_market_open():
            logger.info(
                f"⏩ Skipping '{job_name}': forex market is closed."
            )
            return
        try:
            job(*args, **kwargs)
        except Exception as e:
            logger.error(f"Job '{job_name}' failed: {e}")
            notify("job_failed", {
                "job_name": job_name,
                "error": str(e),
            })

    return _runner


def _compute_next_run_time(interval_minutes: int, offset_minutes: int = 0, offset_seconds: int = 0) -> datetime:
    interval_seconds = interval_minutes * 60
    offset_total = offset_minutes * 60 + offset_seconds

    now = datetime.now(timezone.utc)
    now_seconds = int(now.timestamp())
    cycles = ((now_seconds - offset_total) // interval_seconds) + 1
    next_seconds = (cycles * interval_seconds) + offset_total
    return datetime.fromtimestamp(next_seconds, tz=timezone.utc)


def compute_first_run_time(timeframe: str, interval_minutes: int, offset_seconds: int) -> datetime:
    """
    Compute the FIRST run based on the ACTUAL broker candle closes.
    """
    df = fetch_data(
        STUB_FOREX_SYMBOL,
        TIMEFRAMES[timeframe],
        1,
        timeframe_label=timeframe,
        closed_candles_only=False,
    )
    if df is None or df.empty:
        logger.error(
            "Unable to determine last close time; scheduling job immediately."
        )
        return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)

    last_close: datetime = df.iloc[-1]["time"]
    next_close = last_close + timedelta(minutes=interval_minutes)
    first_run_time = next_close + timedelta(seconds=offset_seconds)

    # Ensure first run is always in the future to prevent immediate catch-up
    now = datetime.now(timezone.utc)
    if first_run_time <= now:
        # Jump to next interval from now
        first_run_time = now + timedelta(minutes=interval_minutes, seconds=offset_seconds)

    return first_run_time
