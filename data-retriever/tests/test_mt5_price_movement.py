"""
MT5 Price Movement & Slippage Test Suite
=========================================

Tests various price movement scenarios and slippage handling to ensure the trading
system correctly handles price changes during order execution.

This test suite covers:
- Exact price matches
- Slippage within acceptable deviation limits
- Slippage exceeding deviation limits
- Negative slippage scenarios
- Different point values (standard pairs vs JPY pairs)
- Edge cases with very small and very large prices
"""

import sys
import os
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader.trading import MT5Trader
from test_mt5_utils import (
    create_mock_connection, create_symbol_info,
    SYMBOL, log_test
)


def test_price_movement_scenarios():
    """
    Test various price movement scenarios and slippage handling.
    
    This test verifies that the position verification system correctly identifies
    when actual execution prices differ from requested prices, and properly handles
    both acceptable slippage (within deviation) and excessive slippage.
    
    Returns:
        bool: True if all price movement tests passed, False otherwise.
    """
    print("\n" + "=" * 70)
    print("CATEGORY 2: PRICE MOVEMENT & SLIPPAGE SCENARIOS")
    print("=" * 70)
    
    # Create mock connection
    sym_info = create_symbol_info()
    mock_conn = create_mock_connection(symbol_info=sym_info)
    
    trader = MT5Trader(mock_conn)
    
    # Test scenarios: (requested_price, actual_price, point, should_fail)
    scenarios = [
        # Standard EUR/USD scenarios
        (1.10000, 1.10000, 0.00001, False),  # Exact match
        (1.10000, 1.10001, 0.00001, False),  # 1 pip slippage (within deviation)
        (1.10000, 1.10020, 0.00001, False),  # 20 pips (exactly at deviation limit)
        (1.10000, 1.10021, 0.00001, True),   # 21 pips (exceeds deviation)
        (1.10000, 1.10100, 0.00001, True),   # 100 pips (extreme slippage)
        (1.10000, 1.09999, 0.00001, False),  # 1 pip negative slippage
        (1.10000, 1.09980, 0.00001, False),  # 20 pips negative
        (1.10000, 1.09979, 0.00001, True),   # 21 pips negative (exceeds)
        
        # JPY pair scenarios (different point value)
        (110.000, 110.001, 0.01, False),   # JPY pair, 1 pip
        (110.000, 110.200, 0.01, False),    # JPY pair, 20 pips
        (110.000, 110.210, 0.01, True),     # JPY pair, 21 pips
        
        # Edge cases
        (0.00001, 0.00022, 0.00001, True), # Very small prices (21 pips)
        (99999.99, 100000.00, 0.01, False), # Large prices
    ]
    
    passed = 0
    for requested, actual, point_val, should_fail in scenarios:
        # Create new symbol info with correct point value for this scenario
        test_sym_info = create_symbol_info(point=point_val)
        mock_conn.mt5.symbol_info.return_value = test_sym_info
        
        # Create position with actual execution price
        pos = MagicMock(
            ticket=12345, 
            symbol=SYMBOL, 
            sl=1.1, 
            tp=1.2, 
            volume=0.01, 
            price_open=actual
        )
        
        # Mock positions_get to return position when called with ticket
        def mock_positions_get(ticket=None):
            if ticket == 12345:
                return [pos]
            return []
        
        mock_conn.mt5.positions_get = mock_positions_get
        
        # Test position verification with price slippage
        # Patch sys.exit and shutdown_system to prevent actual exit
        with patch('time.sleep'):
            with patch('sys.exit'):
                with patch('system_shutdown.shutdown_system') as mock_shutdown:
                    with patch('externals.meta_trader.position_closing._trading_lock.create_lock'):
                        mock_shutdown.return_value = None
                        result = trader.verify_position_consistency(
                            12345, 1.1, 1.2, expected_volume=0.01, expected_price=requested
                        )
        
        # Verify that verification fails when slippage exceeds limits
        success = (result is False) == should_fail
        log_test(
            f"Price {requested} -> {actual} (point={point_val}, should_fail={should_fail})", 
            success
        )
        if success:
            passed += 1
    
    print(f"\n  Price movement tests: {passed}/{len(scenarios)} passed")
    return passed == len(scenarios)


if __name__ == "__main__":
    test_price_movement_scenarios()
