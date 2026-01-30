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
from notifications import notify

logger = get_logger(__name__)

# Global flag to track if shutdown was requested
_shutdown_requested = False
_shutdown_reason = None


def request_shutdown(reason: str = None):
    """Request the system to shut down gracefully.
    
    This sets a flag that the main loop checks. The actual shutdown
    happens in the finally block of main() to ensure cleanup.
    
    Args:
        reason: Optional reason for the shutdown request.
    """
    global _shutdown_requested, _shutdown_reason
    _shutdown_requested = True
    if reason:
        _shutdown_reason = reason


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested."""
    return _shutdown_requested


def get_shutdown_reason() -> str:
    """Get the reason for shutdown from the trading lock file.
    
    The reason is stored in the trading lock file when shutdown_system()
    is called. If no lock file exists, returns the stored reason (if any).
    
    Returns:
        The shutdown reason string, or None if no reason is available.
    """
    # First, try to read from the trading lock file (most reliable source)
    try:
        from externals.meta_trader.safeguards import _trading_lock
        lock_data = _trading_lock.storage.read_lock_data()
        if lock_data and "reason" in lock_data:
            return lock_data.get("reason")
    except Exception:
        pass  # If we can't read the lock file, fall back to stored reason
    
    # Fall back to stored reason (e.g., from KeyboardInterrupt)
    return _shutdown_reason


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
    
    # Send critical shutdown notification
    notify("critical_shutdown", {
        "reason": reason,
        "component": "TradingSystem",
    })
    
    # Create lock file to prevent trading on restart
    try:
        from externals.meta_trader.safeguards import _trading_lock
        _trading_lock.create_lock(reason)
    except Exception as e:
        logger.critical(f"Failed to create lock file during shutdown: {e}")
    
    # Request shutdown (if main loop is running, it will check this flag)
    request_shutdown(reason)
    
    # Exit the process immediately
    logger.critical("Exiting system due to critical failure...")
    sys.exit(1)
