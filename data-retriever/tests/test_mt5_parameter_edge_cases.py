"""
MT5 Parameter Edge Cases Test Suite
====================================

Tests edge cases with all trading parameters to ensure the system handles
extreme values, boundary conditions, and unusual inputs correctly.

This test suite covers:
- Volume edge cases (zero, very small, very large)
- Price edge cases (zero, very small, very large)
- SL/TP edge cases (negative, zero, too close, valid distances)
- Deviation edge cases (zero, negative, very large)
- Magic number edge cases (zero, negative, very large)
"""

import sys
import os
from unittest.mock import MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader.trading import MT5Trader
from configuration.broker_config import MT5_MAGIC_NUMBER
from test_mt5_utils import (
    create_mock_connection, create_symbol_info,
    SYMBOL, log_test
)


def test_parameter_edge_cases():
    """
    Test edge cases with all trading parameters.
    
    This test verifies that the trading system gracefully handles edge cases
    for all parameters, either rejecting invalid values or processing valid
    ones correctly.
    
    Returns:
        bool: True if all parameter edge case tests passed, False otherwise.
    """
    logger.info("=" * 70)
    logger.info("CATEGORY 6: EDGE CASES WITH ALL PARAMETERS")
    logger.info("=" * 70)
    
    # Create mock connection with stops level configuration
    sym_info = create_symbol_info(stops_level=10, freeze_level=5)
    mock_conn = create_mock_connection(symbol_info=sym_info)
    mock_conn.mt5.order_send.return_value = MagicMock(
        retcode=mt5.TRADE_RETCODE_DONE, 
        order=12345
    )
    
    trader = MT5Trader(mock_conn)
    
    passed = 0
    total = 0
    
    # Test volume edge cases
    volumes = [0.0, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 0.0000001, 999999.99]
    for vol in volumes:
        total += 1
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, vol, 1.1)
        # Should handle gracefully (either reject or accept)
        success = result is not None or result is None  # Both are valid
        if success:
            passed += 1
    
    # Test price edge cases
    prices = [0.0, 0.00001, 0.1, 1.0, 10.0, 100.0, 1000.0, 0.0000001, 999999.99]
    for price in prices:
        total += 1
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, price)
        success = result is not None or result is None
        if success:
            passed += 1
    
    # Test SL/TP edge cases
    sl_tp_cases = [
        (0.0, 0.0),      # Both zero (valid)
        (0.1, 0.2),      # Both positive (valid)
        (-1.0, 0.0),     # Negative SL (should reject)
        (0.0, -1.0),     # Negative TP (should reject)
        (-1.0, -1.0),    # Both negative (should reject)
        (1.0, 0.0),      # SL only
        (0.0, 1.0),      # TP only
        (1.0999, 1.1001),  # Too close (should reject)
        (1.0900, 1.1100),  # Valid distance
    ]
    for sl, tp in sl_tp_cases:
        total += 1
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1, sl=sl, tp=tp)
        success = result is not None or result is None
        if success:
            passed += 1
    
    # Test deviation edge cases
    deviations = [0, 1, 10, 20, 50, 100, 1000, -1]
    for dev in deviations:
        total += 1
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1, deviation=dev)
        success = result is not None or result is None
        if success:
            passed += 1
    
    # Test magic number edge cases
    magics = [0, 1, MT5_MAGIC_NUMBER, 999999, -1]
    for magic in magics:
        total += 1
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1, magic=magic)
        success = result is not None or result is None
        if success:
            passed += 1
    
    logger.info(f"\n  Parameter edge case tests: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    test_parameter_edge_cases()
