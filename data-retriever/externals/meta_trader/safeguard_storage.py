import json
import os
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from logger import get_logger

logger = get_logger(__name__)

# Default lock file location (can be overridden via SAFEGUARD_LOCK_FILE env var)
DEFAULT_LOCK_FILE = Path(__file__).parent.parent.parent / "logs" / "trading_lock.json"
SAFEGUARD_LOCK_FILE: Path = Path(os.getenv("SAFEGUARD_LOCK_FILE", str(DEFAULT_LOCK_FILE)))


class SafeguardStorage:
    """Manages the persistence of the safeguard lock file.
    
    Handles all low-level file I/O operations with thread safety.
    """
    
    _file_lock = threading.Lock()  # Class-level lock for file operations
    
    def __init__(self, lock_file: Path = SAFEGUARD_LOCK_FILE):
        self.lock_file = lock_file
        
    def read_lock_data(self) -> Optional[Dict[str, Any]]:
        """Reads lock data from file.
        
        Returns:
            dict with lock info if file exists and is valid.
            None if file does not exist.
            dict with 'error' key if file exists but is corrupted.
        """
        with self._file_lock:
            if not self.lock_file.exists():
                return None
            
            try:
                with open(self.lock_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError, OSError, PermissionError) as e:
                # Log here, but return error state so validation logic knows
                logger.error(f"Lock file corrupted: {e}")
                return {"error": str(e)}

    def write_lock_file(self, data: Dict[str, Any]) -> None:
        """Writes data to the lock file safely.
        
        Raises:
            RuntimeError: If writing fails (critical safety issue).
        """
        with self._file_lock:
            try:
                # Ensure parent directory exists
                self.lock_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(self.lock_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except (IOError, OSError, PermissionError) as e:
                # Critical logging handled by caller or here? 
                # Better to log IO failure here too.
                logger.critical(f"Failed to create lock file at {self.lock_file}: {e}")
                raise RuntimeError(f"CRITICAL: Failed to create trading lock: {e}") from e

    def delete_lock_file(self) -> bool:
        """Deletes the lock file if it exists.
        
        Returns:
            True if file was deleted, False if it didn't exist or deletion failed.
        """
        with self._file_lock:
            if not self.lock_file.exists():
                return False
            
            try:
                self.lock_file.unlink()
                return True
            except (IOError, OSError, PermissionError) as e:
                logger.error(f"Failed to delete trading lock at {self.lock_file}: {e}")
                return False
                
    def exists(self) -> bool:
        """Checks if lock file exists (thread-safe)."""
        with self._file_lock:
            return self.lock_file.exists()
