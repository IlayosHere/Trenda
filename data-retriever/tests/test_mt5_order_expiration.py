"""
MT5 Order Expiration & Timing Test Suite
=========================================

Tests order expiration scenarios to ensure orders are properly configured with
correct expiration times based on current market time.

This test suite covers:
- Expiration time calculation from current tick time
- Various expiration durations (0s, 10s, 60s, 300s)
- Edge cases with zero and very large expiration times
- Timestamp boundary conditions
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


def test_order_expiration_scenarios():
    """
    Test order expiration scenarios and timing calculations.
    
    This test verifies that expiration times are correctly calculated by adding
    the specified expiration seconds to the current tick time, and that the
    calculated expiration is properly included in the order request.
    
    Returns:
        bool: True if all expiration tests passed, False otherwise.
    """
    logger.info("=" * 70)
    logger.info("CATEGORY 3: ORDER EXPIRATION & TIMING SCENARIOS")
    logger.info("=" * 70)
    
    # Create mock connection
    sym_info = create_symbol_info()
    mock_conn = create_mock_connection(symbol_info=sym_info)
    
    trader = MT5Trader(mock_conn)
    
    # Test different expiration scenarios: (current_time, expiration_seconds, expected_expiration)
    scenarios = [
        (1000, 10, 1010),      # Standard: 10 seconds
        (1000, 0, 1000),       # Zero expiration
        (1000, 60, 1060),      # 1 minute
        (1000, 300, 1300),     # 5 minutes
        (0, 10, 10),           # Starting from zero
        (999999999, 10, 1000000009),  # Very large timestamp
    ]
    
    passed = 0
    for current_time, exp_seconds, expected_exp in scenarios:
        # Configure tick to return specific time
        mock_conn.mt5.symbol_info_tick.return_value = MagicMock(time=current_time)
        mock_conn.mt5.order_send.return_value = MagicMock(
            retcode=mt5.TRADE_RETCODE_DONE, 
            order=12345
        )
        
        # Place order with specified expiration
        result = trader.place_order(
            SYMBOL, 
            mt5.ORDER_TYPE_BUY, 
            0.01, 
            1.1, 
            expiration_seconds=exp_seconds
        )
        
        if result:
            # Verify expiration time in order request
            call_args = mock_conn.mt5.order_send.call_args[0][0]
            actual_exp = call_args.get('expiration', 0)
            success = actual_exp == expected_exp
            log_test(
                f"Expiration: time={current_time}, seconds={exp_seconds} -> {expected_exp}", 
                success
            )
            if success:
                passed += 1
        else:
            log_test(
                f"Expiration: time={current_time}, seconds={exp_seconds}", 
                False
            )
    
    logger.info(f"\n  Expiration tests: {passed}/{len(scenarios)} passed")
    return passed == len(scenarios)


if __name__ == "__main__":
    test_order_expiration_scenarios()
