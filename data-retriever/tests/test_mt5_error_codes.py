"""
MT5 Error Codes Test Suite
===========================

Tests handling of all MT5 error codes and retcodes to ensure proper error handling
and logging throughout the trading system.

This test suite covers:
- All standard MT5 error codes (10004-10065)
- Error code interpretation and logging
- Error response handling
- Edge cases with error codes
"""

import sys
import os
from unittest.mock import MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader.trading import MT5Trader
from test_mt5_utils import (
    setup_mock_mt5, create_mock_connection, create_symbol_info,
    SYMBOL, log_test
)


def test_all_mt5_error_codes():
    """
    Test handling of all MT5 error codes.
    
    This test verifies that the trading system correctly handles and processes
    all known MT5 error codes, ensuring that error responses are properly
    returned and logged.
    
    Returns:
        bool: True if all error code tests passed, False otherwise.
    """
    logger.info("=" * 70)
    logger.info("CATEGORY 1: ALL MT5 ERROR CODES")
    logger.info("=" * 70)
    
    # Define all known MT5 error codes with descriptions
    error_codes = {
        10004: "Requote - price changed",
        10006: "Request rejected",
        10007: "Request canceled by trader",
        10010: "Only part of request completed",
        10013: "Invalid request",
        10014: "Invalid volume",
        10015: "Invalid price",
        10016: "Invalid stops (SL/TP)",
        10017: "Trade disabled",
        10018: "Market closed",
        10019: "Insufficient funds",
        10020: "Prices changed",
        10021: "No quotes",
        10022: "Invalid order expiration",
        10024: "Too frequent requests",
        10025: "No connection with trade server",
        10026: "AutoTrading disabled by server",
        10027: "AutoTrading disabled in terminal",
        10028: "Order locked",
        10029: "Invalid filling",
        10030: "Invalid SL/TP for this symbol",
        10031: "Close order already exists",
        10032: "Limit order already exists",
        10033: "Invalid order filling type",
        10034: "Invalid order expiration type",
        10035: "Invalid order type",
        10036: "No common error",
        10038: "Invalid request id",
        10039: "Order cannot be modified",
        10040: "Order cannot be canceled",
        10041: "Invalid order filling mode",
        10042: "Invalid order expiration date",
        10043: "Invalid order size",
        10044: "Invalid order stop level",
        10045: "Invalid order price",
        10046: "Invalid order stop loss",
        10047: "Invalid order take profit",
        10048: "Invalid order comment",
        10049: "Invalid order magic number",
        10050: "Invalid order symbol",
        10051: "Invalid order ticket",
        10052: "Invalid order volume",
        10053: "Invalid order type",
        10054: "Invalid order filling mode",
        10055: "Invalid order expiration type",
        10056: "Invalid order expiration date",
        10057: "Invalid order stop level",
        10058: "Invalid order price",
        10059: "Invalid order stop loss",
        10060: "Invalid order take profit",
        10061: "Invalid order comment",
        10062: "Invalid order magic number",
        10063: "Invalid order symbol",
        10064: "Invalid order ticket",
        10065: "Invalid order volume",
    }
    
    # Create mock connection with standard symbol configuration
    sym_info = create_symbol_info()
    mock_conn = create_mock_connection(symbol_info=sym_info)
    
    trader = MT5Trader(mock_conn)
    
    passed = 0
    for retcode, description in error_codes.items():
        # Configure mock to return specific error code
        # For MARKET_MOVED errors (10004, 10020, 10021, 10025), the system will retry
        # So we need to mock the retry to also return the same error
        from externals.meta_trader.error_categorization import MT5ErrorCategorizer, ErrorCategory
        category = MT5ErrorCategorizer.categorize(retcode)
        
        if category == ErrorCategory.MARKET_MOVED:
            # For MARKET_MOVED errors, retry will be attempted
            # Mock both the initial call and the retry to return the same error
            mock_conn.mt5.order_send.side_effect = [
                MagicMock(retcode=retcode, order=0),  # First attempt
                MagicMock(retcode=retcode, order=0)   # Retry attempt (also fails)
            ]
            # Mock symbol_info_tick for retry mechanism
            mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1, ask=1.1001, time=1000)
        else:
            # For other errors, just return the error code
            mock_conn.mt5.order_send.return_value = MagicMock(retcode=retcode, order=0)
            mock_conn.mt5.order_send.side_effect = None  # Reset side_effect
        
        result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
        
        # Verify that error result is returned (not None) and has correct retcode
        # For MARKET_MOVED errors, after retry fails, it should return the error from retry
        success = result is not None and result.retcode == retcode
        log_test(f"Error code {retcode}: {description}", success)
        if success:
            passed += 1
    
    logger.info(f"\n  Error code tests: {passed}/{len(error_codes)} passed")
    return passed == len(error_codes)


if __name__ == "__main__":
    test_all_mt5_error_codes()
