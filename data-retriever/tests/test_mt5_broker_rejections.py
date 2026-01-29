"""
MT5 Broker Rejections & Market Conditions Test Suite
=====================================================

Tests broker rejection scenarios and market condition handling to ensure the
trading system correctly processes and handles broker rejections.

This test suite covers:
- Market closed rejections
- Insufficient funds rejections
- AutoTrading disabled rejections
- Other broker-side rejection scenarios
"""

import sys
import os
from unittest.mock import MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader.trading import MT5Trader
from test_mt5_utils import (
    create_mock_connection, create_symbol_info,
    SYMBOL, log_test
)


def test_broker_rejection_scenarios():
    """
    Test broker rejection scenarios and market condition handling.
    
    This test verifies that the trading system correctly handles various broker
    rejection scenarios, ensuring that rejection error codes are properly
    returned and can be processed by the calling code.
    
    Returns:
        bool: True if all broker rejection tests passed, False otherwise.
    """
    print("\n" + "=" * 70)
    print("CATEGORY 5: BROKER REJECTIONS & MARKET CONDITIONS")
    print("=" * 70)
    
    # Create mock connection
    sym_info = create_symbol_info()
    mock_conn = create_mock_connection(symbol_info=sym_info)
    
    trader = MT5Trader(mock_conn)
    
    passed = 0
    total = 3
    
    # Test market closed rejection (error code 10018)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10018)
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    success = result is not None and result.retcode == 10018
    log_test("Market closed rejection", success)
    if success:
        passed += 1
    
    # Test insufficient funds rejection (error code 10019)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10019)
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    success = result is not None and result.retcode == 10019
    log_test("Insufficient funds rejection", success)
    if success:
        passed += 1
    
    # Test AutoTrading disabled rejection (error code 10026)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10026)
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    success = result is not None and result.retcode == 10026
    log_test("AutoTrading disabled rejection", success)
    if success:
        passed += 1
    
    print(f"\n  Broker rejection tests: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    test_broker_rejection_scenarios()
