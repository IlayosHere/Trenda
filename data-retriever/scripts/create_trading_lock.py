#!/usr/bin/env python3
"""Script to manually create a trading lock file.

Usage:
    python scripts/create_trading_lock.py [reason]
    
Example:
    python scripts/create_trading_lock.py "Manual pause for maintenance"
    
If no reason is provided, will prompt for one.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from externals.meta_trader.safeguards import _trading_lock
from logger import get_logger

logger = get_logger(__name__)

def main():
    """Create a trading lock file."""
    # Check current status
    status = _trading_lock.is_trading_allowed()
    if not status.is_allowed:
        logger.warning(f"Trading is already LOCKED: {status.reason}")
        response = input("Replace existing lock? (y/n): ").strip().lower()
        if not response.startswith('y'):
            logger.info("Cancelled by user")
            return 1
    
    # Get reason
    if len(sys.argv) > 1:
        reason = " ".join(sys.argv[1:])
    else:
        reason = input("Enter reason for locking trading: ").strip()
        if not reason:
            logger.error("Reason cannot be empty")
            return 1
    
    # Create the lock
    try:
        _trading_lock.create_lock(reason)
        logger.warning(f"Trading lock created - trading is now PAUSED. Reason: {reason}")
        return 0
    except Exception as e:
        logger.error(f"Failed to create lock: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
