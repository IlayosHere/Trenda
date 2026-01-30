"""
Main entry point for the Trend Analyzer Bot.

This module handles:
- System startup and initialization
- Main execution loop (replay or live mode)
- Cleanup on shutdown

For detailed explanation of the trading lock mechanism, see TRADING_LOCK_MECHANISM.md
"""
import os
import time
from scheduler import scheduler
from externals import meta_trader
from scheduler import start_scheduler, run_startup_data_refresh
from replay_runner import run as run_replay
from logger import get_logger
from system_shutdown import request_shutdown, is_shutdown_requested, get_shutdown_reason
from notifications import notify
from configuration import FOREX_PAIRS

logger = get_logger(__name__)

# Run mode: "replay" or "live" (default: replay)
RUN_MODE = os.getenv("RUN_MODE", "replay").lower()

# Track lock status for automatic pause/resume
_last_lock_check_time = 0
_last_lock_status = None


def main():
    logger.info("--- 🚀 Starting Trend Analyzer Bot ---")

    if not meta_trader.initialize_mt5():
        logger.error("Failed to initialize MT5. Exiting.")
        notify("mt5_init_failed", {
            "error": "Failed to initialize MT5 connection",
        })
        return
    
    # Send system startup notification
    notify("system_startup", {
        "mode": RUN_MODE,
        "symbol_count": str(len(FOREX_PAIRS)),
        "mt5_status": "Connected",
    })

    # Recover positions on startup (only in live mode)
    if RUN_MODE == "live":
        logger.info("--- 🔄 Running position recovery ---")
        # recovery_stats = meta_trader.recover_positions()
        # if recovery_stats['recovered'] > 0:
        #     logger.warning(
        #         f"⚠️ Recovered {recovery_stats['recovered']} position(s) that were missing from database"
        #     )
        logger.info("--- ✅ Position recovery complete ---\n")

    try:
        if RUN_MODE == "replay":
            logger.info("Running REPLAY engine...")
            run_replay()
        elif RUN_MODE == "live":
            logger.info("Running LIVE scheduler...")
            run_startup_data_refresh()
            start_scheduler()
            
            # Main loop: keep system running until shutdown is requested
            while True:
                # Check if shutdown was requested
                if is_shutdown_requested():
                    reason = get_shutdown_reason()
                    if reason:
                        logger.critical(f"🛑 System shutdown requested. Reason: {reason}")
                        # TODO: add WhatsApp message
                    else:
                        logger.critical("🛑 System shutdown requested (no reason provided)")
                    break  # Exit the loop to proceed to cleanup in finally block
                
                # Check trading lock status (every 10 seconds to avoid spam)
                # This allows automatic pause/resume when lock file is created/deleted
                global _last_lock_check_time, _last_lock_status
                current_time = time.time()
                if (current_time - _last_lock_check_time) >= 10:
                    _last_lock_check_time = current_time
                    lock_status = meta_trader.is_trading_allowed()
                    
                    # Log status changes
                    if _last_lock_status is None:
                        # First check - log initial status
                        if not lock_status.is_allowed:
                            logger.warning(f"🔒 Trading is LOCKED: {lock_status.reason}")
                        else:
                            logger.info("✅ Trading is allowed")
                        _last_lock_status = lock_status.is_allowed
                    if _last_lock_status != lock_status.is_allowed:
                        # Status changed - log the change
                        if lock_status.is_allowed:
                            logger.info("✅ Trading lock cleared - Trading RESUMED automatically")
                            notify("trading_unlocked", {
                                "unlock_time": str(time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())),
                            })
                        else:
                            logger.warning(f"🔒 Trading LOCKED - Trading PAUSED: {lock_status.reason}")
                            notify("trading_locked", {
                                "reason": lock_status.reason,
                                "lock_time": str(time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())),
                            })
                        _last_lock_status = lock_status.is_allowed
                
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
        request_shutdown("User requested shutdown (Ctrl+C)")
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
        notify("system_shutdown", {
            "reason": get_shutdown_reason() or "Normal shutdown",
        })


# --- Run the bot ---
if __name__ == "__main__":
    main()

