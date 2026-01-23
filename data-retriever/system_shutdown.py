"""System shutdown handler for critical failures.

This module provides a simple way to shut down the entire trading system
when a critical failure occurs (e.g., position cannot be closed).

The shutdown process:
1. Logs the critical error
2. Creates a lock file to prevent trading on restart
3. Exits the process
"""
import sys
from logger import get_logger

logger = get_logger(__name__)

# Global flag to track if shutdown was requested
_shutdown_requested = False


def request_shutdown():
    """Request the system to shut down gracefully.
    
    This sets a flag that the main loop checks. The actual shutdown
    happens in the finally block of main() to ensure cleanup.
    """
    global _shutdown_requested
    _shutdown_requested = True


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested."""
    return _shutdown_requested


def shutdown_system(reason: str):
    """Shut down the entire trading system immediately.
    
    This function:
    1. Logs the critical error that triggered shutdown
    2. Creates a lock file to prevent trading on restart
    3. Requests system shutdown (if main loop is running)
    4. Exits the process
    
    Args:
        reason: Clear explanation of why the system is shutting down
    """
    logger.critical(f"🛑 SYSTEM SHUTDOWN: {reason}")
    
    # Create lock file to prevent trading on restart
    try:
        from externals.meta_trader.safeguards import _trading_lock
        _trading_lock.create_lock(reason)
    except Exception as e:
        logger.critical(f"Failed to create lock file during shutdown: {e}")
    
    # Request shutdown (if main loop is running, it will check this flag)
    request_shutdown()
    
    # Exit the process immediately
    logger.critical("Exiting system due to critical failure...")
    sys.exit(1)
