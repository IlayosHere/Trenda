import os
import core.env
import time
from scheduler import scheduler
from externals import meta_trader
from scheduler import start_scheduler, run_startup_data_refresh
from replay_runner import run as run_replay
from logger import get_logger

logger = get_logger(__name__)

# Run mode: "replay" or "live" (default: replay)
RUN_MODE = os.getenv("RUN_MODE", "replay").lower()


def main():
    logger.info("--- 🚀 Starting Trend Analyzer Bot ---")

    if not meta_trader.initialize_mt5():
        return  # Exit if MT5 can't start

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
        meta_trader.shutdown_mt5()


# --- Run the bot ---
if __name__ == "__main__":
    main()

