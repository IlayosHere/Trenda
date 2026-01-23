"""
Main entry point for the Trend Analyzer Bot.

This module handles:
- System startup and initialization
- Main execution loop (replay or live mode)
- Cleanup on shutdown

For detailed explanation of the trading lock mechanism, see TRADING_LOCK_MECHANISM.md
"""
import os
import sys
import core.env
import time
from scheduler import scheduler
from externals import meta_trader
from scheduler import start_scheduler, run_startup_data_refresh
from replay_runner import run as run_replay
from logger import get_logger
from system_shutdown import request_shutdown, is_shutdown_requested

logger = get_logger(__name__)

# Run mode: "replay" or "live" (default: replay)
RUN_MODE = os.getenv("RUN_MODE", "replay").lower()


def main():
    logger.info("--- 🚀 Starting Trend Analyzer Bot ---")

    if not meta_trader.initialize_mt5():
        logger.error("Failed to initialize MT5. Exiting.")
        return

    try:
        if RUN_MODE == "replay":
            logger.info("Running REPLAY engine...")
            run_replay()
        elif RUN_MODE == "live":
            logger.info("Running LIVE scheduler...")
            run_startup_data_refresh()
            start_scheduler()
            
            # Main loop: keep system running until shutdown is requested
            while not is_shutdown_requested():
                time.sleep(1)  # Check shutdown flag every second
                
                # Health check: warn if scheduler has no jobs
                if scheduler.running and not scheduler.get_jobs():
                    logger.warning("Scheduler is running but has no scheduled jobs")
        else:
            logger.error(f"Unknown RUN_MODE: {RUN_MODE}. Must be 'replay' or 'live'.")
            return

    except KeyboardInterrupt:
        # User pressed Ctrl+C - stop the system
        logger.info("Shutdown requested by user (Ctrl+C)")
        request_shutdown()
    except Exception as e:
        logger.exception(f"Critical error in main: {e}")
        raise  # Re-raise to trigger finally block for cleanup

    finally:
        # Always clean up resources, even if there was an error
        logger.info("Cleaning up and shutting down services...")
        
        # Shutdown scheduler
        if scheduler.running:
            try:
                scheduler.shutdown(wait=True)
                logger.info("Scheduler stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping scheduler: {e}")
        
        # Shutdown MT5 connection
        try:
            meta_trader.shutdown_mt5()
            logger.info("MT5 connection closed successfully")
        except Exception as e:
            logger.error(f"Error closing MT5 connection: {e}")
        
        logger.info("--- ✅ System shutdown complete ---")


# --- Run the bot ---
if __name__ == "__main__":
    main()

