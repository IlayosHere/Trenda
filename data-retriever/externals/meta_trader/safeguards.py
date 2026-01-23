"""Trading lock system to prevent trading after critical failures.

This module provides a simple lock file system that persists across restarts.
If a critical failure occurs (e.g., position cannot be closed), a lock file
is created. On restart, the system checks for this lock file and refuses to
trade until the lock is manually cleared.

The lock file is a JSON file stored in the logs directory.
"""
from datetime import datetime, timezone

from logger import get_logger
from .safeguard_types import SafeguardStatus
from .safeguard_storage import SafeguardStorage

logger = get_logger(__name__)


class TradingLock:
    """Manages a persistent lock file to prevent trading after critical failures.
    
    When a critical failure occurs (e.g., position close fails), a lock file
    is created. This file persists across restarts, so the system won't trade
    again until the lock is manually cleared.
    
    The lock file contains:
    - reason: Why trading was locked
    - timestamp: When it was locked
    - locked_by: Which component locked it
    """
    
    def __init__(self, storage: SafeguardStorage = None):
        self.storage = storage or SafeguardStorage()
    
    def is_trading_allowed(self) -> SafeguardStatus:
        """Check if trading is currently allowed.
        
        Returns:
            SafeguardStatus with is_allowed=True if no lock file exists,
            or is_allowed=False with reason if lock file exists.
        """
        lock_data = self.storage.read_lock_data()
        
        # No lock file = trading is allowed
        if lock_data is None:
            return SafeguardStatus(True, "")
        
        # Lock file exists but is corrupted = block trading for safety
        if "error" in lock_data:
            error_msg = lock_data.get("error", "Unknown error")
            logger.error(f"Lock file is corrupted: {error_msg}. Blocking trading for safety.")
            return SafeguardStatus(False, f"Lock file corrupted: {error_msg}")
        
        # Lock file exists and is valid = trading is blocked
        reason = lock_data.get("reason", "Unknown reason")
        locked_at = lock_data.get("timestamp", "Unknown time")
        return SafeguardStatus(False, f"{reason} (locked at {locked_at})")
    
    def create_lock(self, reason: str) -> None:
        """Create a lock file to prevent trading.
        
        This is called when a critical failure occurs. The lock file will
        prevent trading on the next restart until it's manually cleared.
        
        Args:
            reason: Clear explanation of why trading is being locked.
            
        Raises:
            RuntimeError: If the lock file cannot be created.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        lock_data = {
            "reason": reason,
            "timestamp": timestamp,
            "locked_by": "TradingLock"
        }
        
        try:
            self.storage.write_lock_file(lock_data)
            logger.critical(
                f"🔒 TRADING LOCKED: {reason} | "
                f"Lock file: {self.storage.lock_file} | "
                f"To resume trading, delete the lock file or call clear_lock()"
            )
        except RuntimeError as e:
            logger.critical(f"❌ CRITICAL: Failed to create lock file: {e}")
            raise
    
    def clear_lock(self) -> bool:
        """Remove the lock file to allow trading again.
        
        Returns:
            True if lock was cleared, False if no lock existed.
        """
        if self.storage.delete_lock_file():
            logger.info("✅ Trading lock cleared. Trading can resume.")
            return True
        else:
            if not self.storage.exists():
                logger.info("No trading lock to clear.")
            return False
    
    def is_locked(self) -> bool:
        """Check if trading is currently locked."""
        return not self.is_trading_allowed().is_allowed


# Global instance - use this throughout the codebase
_trading_lock = TradingLock()
