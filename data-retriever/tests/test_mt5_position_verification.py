"""
MT5 Position Verification Edge Cases Test Suite
================================================

Tests position verification edge cases to ensure the system correctly
verifies position parameters and handles mismatches.

This test suite covers:
- Missing position verification
- SL/TP mismatch detection
- Volume mismatch detection
- Price slippage detection
- Exact match verification
"""

import sys
import os
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mt5_wrapper import mt5
from externals.meta_trader.trading import MT5Trader
from test_mt5_utils import (
    create_mock_connection, create_symbol_info,
    SYMBOL, log_test
)
from logger import get_logger
logger = get_logger(__name__)



def test_position_verification_edge_cases():
    """
    Test position verification edge cases.
    
    This test verifies that the position verification system correctly identifies
    mismatches in SL/TP, volume, and price, and triggers position closure
    when mismatches are detected.
    
    Returns:
        bool: True if all position verification tests passed, False otherwise.
    """
    logger.info("=" * 70)
    logger.info("CATEGORY 10: POSITION VERIFICATION EDGE CASES")
    logger.info("=" * 70)
    
    sym_info = create_symbol_info()
    mock_conn = create_mock_connection(symbol_info=sym_info)
    
    trader = MT5Trader(mock_conn)
    
    passed = 0
    total = 0
    
    # Test missing position - should return True (position already closed)
    mock_conn.mt5.positions_get = MagicMock(return_value=[])  # No positions
    with patch('time.sleep'):
        with patch('sys.exit'):
            with patch('system_shutdown.shutdown_system'):
                with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                    result = trader.verify_position_consistency(12345, 1.1, 1.2)
    total += 1
    if result is True:  # Should return True for missing position
        passed += 1
    log_test("Missing position verification", result is True)
    
    # Test SL mismatch - should trigger close
    pos = MagicMock(symbol=SYMBOL, sl=1.15, tp=1.2, volume=0.01, price_open=1.1, type=mt5.POSITION_TYPE_BUY)
    # Setup mock to make close_position succeed
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1, ask=1.1)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    # Setup positions_get to return position first, then empty after close
    call_count = [0]
    def mock_pos_get(ticket=None):
        call_count[0] += 1
        if ticket == 12345:
            # First call: return position (for verification)
            # Subsequent calls: return empty (position closed)
            if call_count[0] == 1:
                return [pos]
            return []
        return []
    mock_conn.mt5.positions_get = mock_pos_get
    mock_conn.mt5.symbol_info.return_value = sym_info
    with patch('time.sleep'):
        with patch('sys.exit'):
            with patch('system_shutdown.shutdown_system'):
                with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                    result = trader.verify_position_consistency(12345, 1.1, 1.2)
    total += 1
    if result is False:
        passed += 1
    log_test("SL mismatch triggers close", result is False)
    
    # Test TP mismatch - should trigger close
    pos = MagicMock(symbol=SYMBOL, sl=1.1, tp=1.25, volume=0.01, price_open=1.1, type=mt5.POSITION_TYPE_BUY)
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1, ask=1.1)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    call_count = [0]
    def mock_pos_get(ticket=None):
        call_count[0] += 1
        if ticket == 12345:
            if call_count[0] == 1:
                return [pos]
            return []
        return []
    mock_conn.mt5.positions_get = mock_pos_get
    mock_conn.mt5.symbol_info.return_value = sym_info
    with patch('time.sleep'):
        with patch('sys.exit'):
            with patch('system_shutdown.shutdown_system'):
                with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                    result = trader.verify_position_consistency(12345, 1.1, 1.2)
    total += 1
    if result is False:
        passed += 1
    log_test("TP mismatch triggers close", result is False)
    
    # Test volume mismatch - should trigger close
    pos = MagicMock(symbol=SYMBOL, sl=1.1, tp=1.2, volume=0.02, price_open=1.1, type=mt5.POSITION_TYPE_BUY)
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1, ask=1.1)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    call_count = [0]
    def mock_pos_get(ticket=None):
        call_count[0] += 1
        if ticket == 12345:
            if call_count[0] == 1:
                return [pos]
            return []
        return []
    mock_conn.mt5.positions_get = mock_pos_get
    mock_conn.mt5.symbol_info.return_value = sym_info
    with patch('time.sleep'):
        with patch('sys.exit'):
            with patch('system_shutdown.shutdown_system'):
                with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                    result = trader.verify_position_consistency(
                        12345, 1.1, 1.2, expected_volume=0.01
                    )
    total += 1
    if result is False:
        passed += 1
    log_test("Volume mismatch triggers close", result is False)
    
    # Test price slippage - should trigger close
    pos = MagicMock(
        symbol=SYMBOL, 
        sl=1.1, 
        tp=1.2, 
        volume=0.01, 
        price_open=1.1021,  # Exceeds deviation (0.0001 * 20 = 0.002, actual is 0.0021)
        type=mt5.POSITION_TYPE_BUY
    )
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1, ask=1.1)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    call_count = [0]
    def mock_pos_get(ticket=None):
        call_count[0] += 1
        if ticket == 12345:
            if call_count[0] == 1:
                return [pos]
            return []
        return []
    mock_conn.mt5.positions_get = mock_pos_get
    mock_conn.mt5.symbol_info.return_value = sym_info
    with patch('time.sleep'):
        with patch('sys.exit'):
            with patch('system_shutdown.shutdown_system'):
                with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                    result = trader.verify_position_consistency(
                        12345, 1.1, 1.2, expected_price=1.1
                    )
    total += 1
    if result is False:
        passed += 1
    log_test("Price slippage triggers close", result is False)
    
    # Test exact match - should pass verification
    pos = MagicMock(symbol=SYMBOL, sl=1.1, tp=1.2, volume=0.01, price_open=1.1)
    mock_conn.mt5.positions_get = MagicMock(return_value=[pos])
    mock_conn.mt5.symbol_info.return_value = sym_info
    with patch('time.sleep'):
        with patch('sys.exit'):
            with patch('system_shutdown.shutdown_system'):
                with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                    result = trader.verify_position_consistency(
                        12345, 1.1, 1.2, expected_volume=0.01, expected_price=1.1
                    )
    total += 1
    if result is True:
        passed += 1
    log_test("Exact match verification", result is True)
    
    logger.info(f"\n  Position verification tests: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    test_position_verification_edge_cases()
