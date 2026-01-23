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
        """Writes data to the lock file safely with atomic write.
        
        Uses atomic write pattern: write to temp file, then rename to ensure
        file is either fully written or not present (no partial writes).
        
        Raises:
            RuntimeError: If writing fails (critical safety issue).
        """
        with self._file_lock:
            temp_file = None
            try:
                # Ensure parent directory exists
                try:
                    self.lock_file.parent.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError) as e:
                    logger.critical(f"Failed to create lock file directory {self.lock_file.parent}: {e}")
                    raise RuntimeError(f"CRITICAL: Failed to create lock directory: {e}") from e
                
                # Atomic write: write to temp file first, then rename
                # Use a unique temp filename to avoid conflicts
                import uuid
                temp_file = self.lock_file.parent / f"{self.lock_file.stem}.{uuid.uuid4().hex[:8]}.tmp"
                try:
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)
                        f.flush()
                        # Ensure data is written to disk before renaming
                        os.fsync(f.fileno())
                    
                    # On Windows, we may need to delete the target file first if it exists
                    # This is safe because we're replacing it with the same content
                    if self.lock_file.exists():
                        try:
                            self.lock_file.unlink()
                        except (OSError, PermissionError) as e:
                            # If we can't delete, try rename anyway (might work on some systems)
                            logger.warning(f"Could not delete existing lock file before rename: {e}")
                            # Try rename anyway - on Unix it will work, on Windows it might fail
                            try:
                                temp_file.replace(self.lock_file)
                            except (OSError, PermissionError):
                                # If rename fails, try direct write as fallback (less atomic but better than nothing)
                                logger.warning("Atomic rename failed, attempting direct write")
                                with open(self.lock_file, 'w', encoding='utf-8') as f:
                                    json.dump(data, f, indent=2)
                                    f.flush()
                                    os.fsync(f.fileno())
                                # Clean up temp file
                                if temp_file.exists():
                                    temp_file.unlink()
                                return
                    
                    # Atomic rename - this is atomic on most filesystems
                    # On Windows, this will work if target doesn't exist or was deleted
                    temp_file.replace(self.lock_file)
                except (IOError, OSError, PermissionError) as e:
                    # Clean up temp file if it exists
                    if temp_file and temp_file.exists():
                        try:
                            temp_file.unlink()
                        except Exception:
                            pass  # Ignore cleanup errors
                    
                    # Try fallback: direct write (less atomic but better than failing completely)
                    try:
                        logger.warning("Atomic write failed, attempting direct write as fallback")
                        with open(self.lock_file, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                            f.flush()
                            os.fsync(f.fileno())
                        logger.info("Direct write succeeded as fallback")
                        return
                    except (IOError, OSError, PermissionError) as fallback_error:
                        logger.critical(f"Failed to write lock file at {self.lock_file}: {e} (fallback also failed: {fallback_error})")
                        raise RuntimeError(f"CRITICAL: Failed to create trading lock: {e}") from e
            except RuntimeError:
                raise  # Re-raise RuntimeError as-is
            except Exception as e:
                # Clean up temp file on any unexpected error
                if temp_file and temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
                logger.critical(f"Unexpected error writing lock file: {e}")
                raise RuntimeError(f"CRITICAL: Unexpected error creating trading lock: {e}") from e

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
