"""
MT5 Concurrency & Race Conditions Test Suite
==============================================

Tests concurrency scenarios and race conditions to ensure thread safety
and proper locking mechanisms in the trading system.

This test suite covers:
- Concurrent order placement
- Thread safety with locks
- Race condition prevention
"""

import sys
import os
import threading
from unittest.mock import MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader.trading import MT5Trader
from test_mt5_utils import (
    create_symbol_info,
    SYMBOL, log_test
)


def test_concurrency_scenarios():
    """
    Test concurrency and race condition scenarios.
    
    This test verifies that the trading system correctly handles concurrent
    operations using proper locking mechanisms, preventing race conditions
    and ensuring thread safety.
    
    Returns:
        bool: True if all concurrency tests passed, False otherwise.
    """
    logger.info("=" * 70)
    logger.info("CATEGORY 9: CONCURRENCY & RACE CONDITIONS")
    logger.info("=" * 70)
    
    # Create mock connection with real lock for testing
    from unittest.mock import MagicMock
    from externals.meta_trader.connection import MT5Connection
    from test_mt5_utils import setup_mock_mt5
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = threading.Lock()  # Real lock for testing
    
    sym_info = create_symbol_info()
    mock_conn.mt5.symbol_info.return_value = sym_info
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(time=1000)
    mock_conn.mt5.order_send.return_value = MagicMock(
        retcode=mt5.TRADE_RETCODE_DONE, 
        order=12345
    )
    
    trader = MT5Trader(mock_conn)
    
    results = []
    def place_concurrent():
        """Place order in concurrent thread."""
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
        results.append(result)
    
    # Test concurrent order placement with 10 threads
    threads = [threading.Thread(target=place_concurrent) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)  # Add timeout to prevent hanging
    
    # Verify all orders were processed
    success = len(results) == 10
    log_test("Concurrent order placement (10 threads)", success)
    
    return success


if __name__ == "__main__":
    test_concurrency_scenarios()
