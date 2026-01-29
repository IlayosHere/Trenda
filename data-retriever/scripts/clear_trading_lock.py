#!/usr/bin/env python3
"""Simple script to clear the trading lock file.

Usage:
    python scripts/clear_trading_lock.py
    
Or from project root:
    python data-retriever/scripts/clear_trading_lock.py
    
The script will:
1. Check current lock status
2. Ask for confirmation
3. Clear the lock file if confirmed
4. System will automatically resume trading (if running)
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from externals.meta_trader.safeguards import _trading_lock
from logger import get_logger

logger = get_logger(__name__)

def main():
    """Clear the trading lock file."""
    # Check current status
    status = _trading_lock.is_trading_allowed()
    if status.is_allowed:
        logger.info("Trading is already allowed (no lock file exists)")
        return 0
    
    logger.warning(f"Trading is currently LOCKED: {status.reason}")
    
    # Ask for confirmation
    response = input("Clear the lock file? (y/n): ").strip().lower()
    if not response.startswith('y'):
        logger.info("Cancelled by user")
        return 1
    
    # Clear the lock
    if _trading_lock.clear_lock():
        logger.info("Trading lock cleared successfully - trading can now resume")
        return 0
    else:
        logger.warning("No lock file to clear (or already cleared)")
        return 0

if __name__ == "__main__":
    sys.exit(main())
