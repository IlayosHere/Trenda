import os
import core.env
import time
from configuration import BROKER_PROVIDER, BROKER_MT5
from scheduler import scheduler
from externals import mt5_handler
from scheduler import start_scheduler, run_startup_data_refresh
from replay_runner import run as run_replay
from logger import get_logger

logger = get_logger(__name__)

# Run mode: "replay" or "live" (default: replay)
RUN_MODE = os.getenv("RUN_MODE", "replay").lower()


def main():
    logger.info("--- 🚀 Starting Trend Analyzer Bot ---")

    if BROKER_PROVIDER == BROKER_MT5:
        if not mt5_handler.initialize_mt5():
            return  # Exit if MT5 can't start
    else:
        logger.info("Using TwelveData broker configuration (MT5 disabled).")

    try:
        if RUN_MODE == "replay":
            logger.info("Running REPLAY engine...")
            run_replay()
        elif RUN_MODE == "live":
            logger.info("Running LIVE scheduler...")
            run_startup_data_refresh()
            start_scheduler()
        else:
            logger.error(f"Unknown RUN_MODE: {RUN_MODE}. Use 'replay' or 'live'.")
            return

        # Keep the main script alive to let the scheduler run
        while True:
            time.sleep(3600)

    except Exception as e:
        logger.error(f"An unexpected error occurred in main: {e}")

    finally:
        # Always shut down MT5 and scheduler
        if scheduler.running:
            scheduler.shutdown()
        if BROKER_PROVIDER == BROKER_MT5:
            mt5_handler.shutdown_mt5()


# --- Run the bot ---
if __name__ == "__main__":
    main()

