"""
MT5 Real-World Trading Scenarios Test Suite
=============================================

Tests real-world trading scenarios that simulate actual market conditions
and common trading situations.

This test suite covers:
- Price movement during order placement
- High market volatility scenarios
- Order expiration before fill
- Partial fill scenarios
- Requote scenarios
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


def test_real_world_scenarios():
    """
    Test real-world trading scenarios.
    
    This test simulates common real-world trading scenarios including price
    movements, volatility, order expiration, partial fills, and requotes.
    
    Returns:
        bool: True if all real-world scenario tests passed, False otherwise.
    """
    print("\n" + "=" * 70)
    print("CATEGORY 12: REAL-WORLD TRADING SCENARIOS")
    print("=" * 70)
    
    passed = 0
    total = 0
    
    # Scenario 1: Price moves during order placement
    sym_info = create_symbol_info()
    mock_conn = create_mock_connection(symbol_info=sym_info)
    
    # Simulate price movement: 1.1000 -> 1.1005 -> 1.1010
    prices = [1.1000, 1.1005, 1.1010]
    price_idx = [-1]  # Start at -1 so first call returns index 0
    
    def get_tick(*args):
        price_idx[0] = (price_idx[0] + 1) % len(prices)
        return MagicMock(
            time=1000, 
            bid=prices[price_idx[0]], 
            ask=prices[price_idx[0]] + 0.0001
        )
    
    mock_conn.mt5.symbol_info_tick.side_effect = get_tick
    mock_conn.mt5.order_send.return_value = MagicMock(
        retcode=mt5.TRADE_RETCODE_DONE, 
        order=12345
    )
    
    trader = MT5Trader(mock_conn)
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, prices[0])
    total += 1
    if result is not None:
        passed += 1
    log_test("Price movement during order", result is not None)
    
    # Scenario 2: Market volatility - rapid price changes
    total += 1
    volatile_prices = [1.1000 + i * 0.0001 for i in range(50)]  # 50 pip movement
    price_idx_vol = [-1]  # Start at -1 so first call returns index 0
    
    def get_volatile_tick(*args):
        price_idx_vol[0] = (price_idx_vol[0] + 1) % len(volatile_prices)
        return MagicMock(
            time=1000, 
            bid=volatile_prices[price_idx_vol[0]], 
            ask=volatile_prices[price_idx_vol[0]] + 0.0001
        )
    
    mock_conn.mt5.symbol_info_tick.side_effect = get_volatile_tick
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, volatile_prices[0])
    if result is not None:
        passed += 1
    log_test("High volatility scenario", result is not None)
    
    # Scenario 3: Order expires before fill
    total += 1
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(time=1000)
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10022)  # Invalid expiration
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1, expiration_seconds=1)
    if result is not None and result.retcode == 10022:
        passed += 1
    log_test("Order expiration before fill", result is not None)
    
    # Scenario 4: Partial fill
    total += 1
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10010)  # Partial fill
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    if result is not None and result.retcode == 10010:
        passed += 1
    log_test("Partial fill scenario", result is not None)
    
    # Scenario 5: Requote scenario
    total += 1
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10004)  # Requote
    result = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    if result is not None and result.retcode == 10004:
        passed += 1
    log_test("Requote scenario", result is not None)
    
    print(f"\n  Real-world scenario tests: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    test_real_world_scenarios()
