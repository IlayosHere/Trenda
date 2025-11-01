from apscheduler.schedulers.background import BackgroundScheduler
from configuration import SCHEDULE_CONFIG
from datetime import datetime, timezone
import utils.display as display

# Create a single, global scheduler instance
scheduler = BackgroundScheduler(daemon=True, timezone="UTC")


def start_scheduler() -> None:
    display.print_status("Starting background scheduler...")

    # Add a job for each timeframe in the config
    for job_name, config  in SCHEDULE_CONFIG.items():
        timeframe = config["timeframe"]
        interval_minutes = config["interval_minutes"]
        job = config["job"]
        display.print_status(
            f"  -> Scheduling job for '{timeframe}': running every {interval_minutes} mins"
        )
        add_job(scheduler, timeframe, interval_minutes, job)

    try:
        scheduler.start()
        display.print_status("✅ Scheduler is running in the background.")
    except Exception as e:
        display.print_error(f"Failed to start scheduler: {e}")


def add_job(scheduler, timeframe, interval_minutes, job):
    scheduler.add_job(
        job,  # The function to call
        "interval",  # The trigger type
        minutes=interval_minutes,
        args=timeframe,  # Arguments to pass to the function
        id=f"job_{timeframe}_{datetime.now()}",  # A unique ID for the job
        replace_existing=True,
        misfire_grace_time=60 * 5,  # Allow job to be 5 mins late
        next_run_time=datetime.now(timezone.utc)
    )
