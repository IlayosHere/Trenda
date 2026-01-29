"""Safeguards package for trading lock management.

This package provides a persistent lock file system that prevents trading
after critical failures. The lock file persists across restarts, ensuring the
system won't trade again until the lock is manually cleared.
"""
from .safeguard_types import SafeguardStatus
from .safeguard_storage import SafeguardStorage
from .safeguards import TradingLock, _trading_lock

__all__ = [
    "SafeguardStatus",
    "SafeguardStorage",
    "TradingLock",
    "_trading_lock",
]
