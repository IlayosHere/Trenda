"""Global trading safeguards and kill-switch for algo trading."""
from datetime import datetime, timezone

from logger import get_logger
from .safeguard_types import SafeguardStatus
from .safeguard_storage import SafeguardStorage

logger = get_logger(__name__)


class TradingSafeguards:
    """Manages global trading kill-switch and safety limits.
    
    The lock is persistent via a JSON file, surviving restarts.
    When locked, algo trading is halted but monitoring/notifications continue.
    Delegates file persistence to SafeguardStorage to separate concerns.
    """
    
    def __init__(self, storage: SafeguardStorage = None):
        self.storage = storage or SafeguardStorage()
    
    def is_trading_allowed(self) -> SafeguardStatus:
        """Check if algo trading is currently allowed.
        
        Returns:
            SafeguardStatus: (is_allowed=True, reason="") if trading is allowed,
                           (is_allowed=False, reason="...") if locked.
        """
        lock_data = self.storage.read_lock_data()
        
        if lock_data is None:
            # File does not exist -> Trading Allowed
            return SafeguardStatus(True, "")
            
        if "error" in lock_data:
            # File exists but corrupted -> Trading Blocked (Safety)
            error_msg = lock_data.get("error", "Unknown IO Error")
            logger.error(f"Lock file corrupted: {error_msg}. Treating as LOCKED for safety.")
            return SafeguardStatus(False, f"Lock file corrupted: {error_msg}")
            
        # File exists and is valid -> Trading Blocked
        reason = lock_data.get("reason", "Unknown reason")
        locked_at = lock_data.get("timestamp", "Unknown time")
        return SafeguardStatus(False, f"{reason} (locked at {locked_at})")
    
    def trigger_emergency_lock(self, reason: str) -> None:
        """Activate the trading kill-switch.
        
        Creates a lock file that persists across restarts.
        Logs a CRITICAL message for immediate attention.
        
        Args:
            reason: Human-readable explanation of why trading was locked.
            
        Raises:
            RuntimeError: If lock file cannot be created (critical safety failure).
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        lock_data = {
            "reason": reason,
            "timestamp": timestamp,
            "locked_by": "TradingSafeguards"
        }
        
        try:
            self.storage.write_lock_file(lock_data)
            
            logger.critical(
                f"🚨 TRADING LOCKED: {reason} | "
                f"Lock file: {self.storage.lock_file} | "
                f"To resume: delete lock file or call clear_lock()"
            )
        except RuntimeError:
            # Logged in storage, but we propagate up to ensure caller knows
            logger.critical(
                f"🚨 FAILED TO CREATE LOCK FILE | "
                f"TRADING MAY CONTINUE UNSAFELY!"
            )
            raise
    
    def clear_lock(self) -> bool:
        """Remove the trading lock to resume algo trading.
        
        Returns:
            True if lock was cleared, False if no lock existed or error.
        """
        if self.storage.delete_lock_file():
            logger.info("✅ Trading lock cleared. Algo trading can resume.")
            return True
        else:
            if not self.storage.exists():
                logger.info("No trading lock to clear.")
            return False
    
    def is_locked(self) -> bool:
        """Simple check if trading is currently locked."""
        return not self.is_trading_allowed().is_allowed


# Singleton instance for global access
_safeguards = TradingSafeguards()
