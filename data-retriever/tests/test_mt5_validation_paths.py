"""
MT5 Validation Path Test Suite
================================

Tests all validation paths in the trading system to ensure proper validation
of symbols, prices, SL/TP distances, and other order parameters.

This test suite covers:
- Symbol validation (invalid symbols, visibility)
- Trade mode validation (disabled, close-only)
- Price validation (zero prices)
- SL/TP validation (negative values, distance requirements)
- Tick info validation failures
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


def test_all_validation_paths():
    """
    Test all validation paths in the trading system.
    
    This test verifies that all validation checks work correctly, rejecting
    invalid orders and allowing valid ones to proceed.
    
    Returns:
        bool: True if all validation path tests passed, False otherwise.
    """
    print("\n" + "=" * 70)
    print("CATEGORY 8: VALIDATION PATH TESTS")
    print("=" * 70)
    
    mock_conn = create_mock_connection()
    trader = MT5Trader(mock_conn)
    
    passed = 0
    total = 0
    
    # Test symbol validation - invalid symbol
    mock_conn.mt5.symbol_info.return_value = None
    result = trader.place_order("INVALID", mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    total += 1
    if result is None:
        passed += 1
    log_test("Invalid symbol rejection", result is None)
    
    # Test symbol visibility - symbol not visible and selection fails
    sym_info = create_symbol_info(visible=False)
    mock_conn.mt5.symbol_info.return_value = sym_info
    mock_conn.mt5.symbol_select.return_value = False  # Selection fails
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    total += 1
    if result is None:
        passed += 1
    log_test("Symbol selection failure", result is None)
    
    # Test trade mode validation - disabled
    # Create a fresh connection to avoid state issues
    mock_conn_disabled = create_mock_connection()
    trader_disabled = MT5Trader(mock_conn_disabled)
    # Use the mock's constant value (which should be set by setup_mock_mt5)
    disabled_mode = mock_conn_disabled.mt5.SYMBOL_TRADE_MODE_DISABLED
    sym_info = create_symbol_info(trade_mode=disabled_mode)
    # Ensure trade_mode is explicitly set (create_symbol_info might default to FULL)
    sym_info.trade_mode = disabled_mode
    mock_conn_disabled.mt5.symbol_info.return_value = sym_info
    mock_conn_disabled.mt5.symbol_select.return_value = True
    mock_conn_disabled.mt5.symbol_info_tick.return_value = MagicMock(time=1000)
    # Reset order_send to track if it's called
    mock_conn_disabled.mt5.order_send.reset_mock()
    result = trader_disabled.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    total += 1
    # Validation should fail before order_send is called, so result should be None
    # and order_send should not be called
    success = result is None and not mock_conn_disabled.mt5.order_send.called
    if success:
        passed += 1
    log_test("Trade mode disabled rejection", success)
    
    # Test trade mode validation - close-only
    sym_info = create_symbol_info(trade_mode=mt5.SYMBOL_TRADE_MODE_CLOSEONLY)
    mock_conn.mt5.symbol_info.return_value = sym_info
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    total += 1
    if result is None:
        passed += 1
    log_test("Trade mode close-only rejection", result is None)
    
    # Test price validation - zero price
    sym_info = create_symbol_info()
    mock_conn.mt5.symbol_info.return_value = sym_info
    mock_conn.mt5.symbol_select.return_value = True
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(time=1000)
    
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 0.0)
    total += 1
    if result is None:
        passed += 1
    log_test("Zero price rejection", result is None)
    
    # Test SL/TP negative validation - negative SL
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1, sl=-1.0)
    total += 1
    if result is None:
        passed += 1
    log_test("Negative SL rejection", result is None)
    
    # Test SL/TP negative validation - negative TP
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1, tp=-1.0)
    total += 1
    if result is None:
        passed += 1
    log_test("Negative TP rejection", result is None)
    
    # Test SL/TP distance validation - SL too close
    sym_info = create_symbol_info(stops_level=10, freeze_level=5)
    mock_conn.mt5.symbol_info.return_value = sym_info
    mock_conn.mt5.symbol_select.return_value = True
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(time=1000)
    # SL too close: min distance is 10 points = 0.0001, but SL is only 0.00005 away (5 points)
    # Price: 1.1000, min_dist: 0.0001, so SL must be <= 1.0999 or >= 1.1001
    # Using SL = 1.09995 which is 0.00005 away (too close)
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1000, sl=1.09995)
    total += 1
    if result is None:
        passed += 1
    log_test("SL too close rejection", result is None)
    
    # Test SL/TP distance validation - TP too close
    # TP too close: min distance is 10 points = 0.0001, but TP is only 0.00005 away (5 points)
    # Using TP = 1.10005 which is 0.00005 away (too close)
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1000, tp=1.10005)
    total += 1
    if result is None:
        passed += 1
    log_test("TP too close rejection", result is None)
    
    # Test tick failure
    mock_conn.mt5.symbol_info_tick.return_value = None
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    total += 1
    if result is None:
        passed += 1
    log_test("Tick info failure", result is None)
    
    print(f"\n  Validation path tests: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    test_all_validation_paths()
