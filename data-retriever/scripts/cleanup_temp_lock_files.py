#!/usr/bin/env python3
"""Cleanup temporary lock files from logs directory.

Removes all trading_lock.*.tmp files, keeping only trading_lock.json.
Uses the built-in cleanup method from TradingLock.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from externals.meta_trader.safeguards import _trading_lock
from logger import get_logger

logger = get_logger(__name__)

def main():
    """Delete all temporary lock files using the built-in cleanup method."""
    logger.info("Cleaning up temporary lock files...")
    
    # Use the built-in cleanup method (deletes files older than 0 hours = all)
    deleted_count = _trading_lock.cleanup_old_temp_files(max_age_hours=0.0)
    
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} temporary lock file(s).")
    else:
        logger.info("No temporary lock files found.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
