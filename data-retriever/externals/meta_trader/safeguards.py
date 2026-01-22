"""Global trading safeguards and kill-switch for algo trading."""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from logger import get_logger

logger = get_logger(__name__)


class SafeguardStatus(NamedTuple):
    """Result of a safeguard check."""
    is_allowed: bool
    reason: str


# Default lock file location (can be overridden via SAFEGUARD_LOCK_FILE env var)
# Note: Avoid placing in logs/ if logs are auto-rotated, as the lock file may be deleted.
# Recommended: Set SAFEGUARD_LOCK_FILE to a dedicated path like /var/lib/trenda/trading_lock.json
DEFAULT_LOCK_FILE = Path(__file__).parent.parent.parent / "logs" / "trading_lock.json"
SAFEGUARD_LOCK_FILE: Path = Path(os.getenv("SAFEGUARD_LOCK_FILE", str(DEFAULT_LOCK_FILE)))


class TradingSafeguards:
    """Manages global trading kill-switch and safety limits.
    
    The lock is persistent via a JSON file, surviving restarts.
    When locked, algo trading is halted but monitoring/notifications continue.
    Thread-safe via internal lock.
    """
    
    _file_lock = threading.Lock()  # Class-level lock for file operations
    
    def __init__(self, lock_file: Path = SAFEGUARD_LOCK_FILE):
        self.lock_file = lock_file
    
    def is_trading_allowed(self) -> SafeguardStatus:
        """Check if algo trading is currently allowed.
        
        Returns:
            SafeguardStatus: (is_allowed=True, reason="") if trading is allowed,
                           (is_allowed=False, reason="...") if locked.
        """
        with self._file_lock:
            if not self.lock_file.exists():
                return SafeguardStatus(True, "")
            
            try:
                with open(self.lock_file, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)
                
                reason = lock_data.get("reason", "Unknown reason")
                locked_at = lock_data.get("timestamp", "Unknown time")
                return SafeguardStatus(False, f"{reason} (locked at {locked_at})")
            
            except (json.JSONDecodeError, IOError, OSError, PermissionError) as e:
                # If lock file is corrupted, treat as locked for safety
                logger.error(f"Lock file corrupted: {e}. Treating as LOCKED for safety.")
                return SafeguardStatus(False, f"Lock file corrupted: {e}")
    
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
        
        with self._file_lock:
            try:
                # Ensure parent directory exists
                self.lock_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(self.lock_file, 'w', encoding='utf-8') as f:
                    json.dump(lock_data, f, indent=2)
                
                logger.critical(
                    f"🚨 TRADING LOCKED: {reason} | "
                    f"Lock file: {self.lock_file} | "
                    f"To resume: delete lock file or call clear_lock()"
                )
            except (IOError, OSError, PermissionError) as e:
                logger.critical(
                    f"🚨 FAILED TO CREATE LOCK FILE: {e} | "
                    f"TRADING MAY CONTINUE UNSAFELY!"
                )
                # Raise to ensure caller knows lock FAILED - critical safety issue
                raise RuntimeError(f"CRITICAL: Failed to create trading lock: {e}") from e
    
    def clear_lock(self) -> bool:
        """Remove the trading lock to resume algo trading.
        
        Returns:
            True if lock was cleared, False if no lock existed or error.
        """
        with self._file_lock:
            if not self.lock_file.exists():
                logger.info("No trading lock to clear.")
                return False
            
            try:
                self.lock_file.unlink()
                logger.info("✅ Trading lock cleared. Algo trading can resume.")
                return True
            except (IOError, OSError, PermissionError) as e:
                logger.error(f"Failed to clear trading lock: {e}")
                return False
    
    def is_locked(self) -> bool:
        """Simple check if trading is currently locked."""
        return not self.is_trading_allowed().is_allowed


# Singleton instance for global access
_safeguards = TradingSafeguards()
