import os
import signal
import sys
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

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    logger.info(f"Received signal {signal_name} ({signum}), initiating graceful shutdown...")
    shutdown_requested = True


def main():
    global shutdown_requested
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("--- 🚀 Starting Trend Analyzer Bot ---")

    if not meta_trader.initialize_mt5():
        logger.error("Failed to initialize MT5. Exiting.")
        return  # Exit if MT5 can't start

    try:
        if RUN_MODE == "replay":
            logger.info("Running REPLAY engine...")
            run_replay()
        elif RUN_MODE == "live":
            logger.info("Running LIVE scheduler...")
            run_startup_data_refresh()
            start_scheduler()
            
            # Keep the main script alive to let the scheduler run
            # Check shutdown flag more frequently for responsive shutdown
            while not shutdown_requested:
                time.sleep(1)  # Check every second instead of hourly
                
                # Optional: Add health check here
                if scheduler.running and not scheduler.get_jobs():
                    logger.warning("Scheduler has no jobs, but still running")
        else:
            logger.error(f"Unknown RUN_MODE: {RUN_MODE}. Use 'replay' or 'live'.")
            return

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user (KeyboardInterrupt)")
        shutdown_requested = True
    except Exception as e:
        logger.exception(f"An unexpected error occurred in main: {e}")  # Use exception() for full stack trace
        raise  # Re-raise to ensure proper shutdown and error propagation

    finally:
        # Always shut down MT5 and scheduler
        logger.info("Shutting down services...")
        if scheduler.running:
            try:
                scheduler.shutdown(wait=True)  # Wait for jobs to complete
                logger.info("Scheduler shut down successfully")
            except Exception as e:
                logger.error(f"Error shutting down scheduler: {e}")
        
        try:
            meta_trader.shutdown_mt5()
            logger.info("MT5 shut down successfully")
        except Exception as e:
            logger.error(f"Error shutting down MT5: {e}")
        
        logger.info("--- ✅ Shutdown complete ---")


# --- Run the bot ---
if __name__ == "__main__":
    main()

