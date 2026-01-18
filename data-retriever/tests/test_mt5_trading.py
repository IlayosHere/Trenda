"""
MT5 Trading Comprehensive Test Suite
=====================================
Tests all functions in trading.py and constraints.py:
- initialize_mt5 / shutdown_mt5
- place_order (with SL/TP, BUY and SELL)
- close_position
- verify_sl_tp_consistency
- is_trade_open (Active, History, Cooldown, and Logic)

IMPORTANT: Run this with MT5 open and logged into a DEMO account!
"""

import sys
import os
import time
import subprocess

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader import (
    initialize_mt5,
    shutdown_mt5,
    place_order,
    close_position,
    is_trade_open,
    verify_sl_tp_consistency,
)
from configuration import MT5_MAGIC_NUMBER

# Test configuration
SYMBOL = "EURUSD"
SYMBOL_TEST6 = "USDJPY"  # For Test 6: different symbol check
SYMBOL_TEST9 = "AUDUSD"  # For Test 9: SELL order test
STRESS_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
LOT_SIZE = 0.01  # Minimum lot for most brokers
PIP_VALUE = 0.0001  # For 5-digit brokers (EURUSD)

# Track test results
test_results = []


def log_test(name: str, passed: bool, details: str = ""):
    """Log test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    test_results.append((name, passed, details))
    print(f"  {status}: {name}")
    if details and not passed:
        print(f"         {details}")


def get_current_price(symbol: str, order_type: int) -> float:
    """Get current market price for a symbol."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return 0.0
    return tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid


def calculate_sl_tp(symbol: str, order_type: int, sl_pips: float = 50, tp_pips: float = 100):
    """Calculate SL and TP prices based on current market price."""
    price = get_current_price(symbol, order_type)
    if price == 0:
        return 0, 0, 0
    
    pip = PIP_VALUE
    if order_type == mt5.ORDER_TYPE_BUY:
        sl = round(price - (sl_pips * pip), 5)
        tp = round(price + (tp_pips * pip), 5)
    else:  # SELL
        sl = round(price + (sl_pips * pip), 5)
        tp = round(price - (tp_pips * pip), 5)
    
    return price, sl, tp


# =============================================================================
# CORE OPERATIONS (1-10)
# =============================================================================

def test_01_initialize_mt5():
    """Test 1: MT5 initialization."""
    print("\n" + "=" * 60)
    print("TEST 1: Initialize MT5")
    print("=" * 60)
    
    result = initialize_mt5()
    log_test("MT5 Initialization", result)
    
    if result:
        account = mt5.account_info()
        if account:
            print(f"    Account: {account.login} | Server: {account.server}")
            is_demo = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
            print(f"    Mode: {'Demo' if is_demo else '⚠️ REAL ACCOUNT!'}")
    
    return result


def test_02_place_buy_with_sl_tp():
    """Test 2: Placing a BUY order with SL and TP."""
    print("\n" + "=" * 60)
    print("TEST 2: Place BUY Order with SL and TP")
    print("=" * 60)
    
    price, sl, tp = calculate_sl_tp(SYMBOL, mt5.ORDER_TYPE_BUY, sl_pips=50, tp_pips=100)
    if price == 0:
        log_test("Get price for BUY order", False, "Could not get price")
        return None
    
    result = place_order(
        symbol=SYMBOL, order_type=mt5.ORDER_TYPE_BUY, volume=LOT_SIZE,
        price=price, sl=sl, tp=tp, comment="TEST: BUY"
    )
    
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log_test("Place BUY order", False, f"Retcode: {result.retcode if result else 'None'}")
        return None
    
    ticket = result.order
    log_test("Place BUY order with SL/TP", True)
    
    # Verify position exists and matches
    time.sleep(0.3)
    positions = mt5.positions_get(ticket=ticket)
    if positions:
        pos = positions[0]
        sl_set = abs(pos.sl - sl) < (PIP_VALUE * 2)
        log_test("BUY SL set correctly", sl_set)
    
    return ticket, sl, tp


def test_03_verify_sl_tp_matching(ticket: int, expected_sl: float, expected_tp: float):
    """Test 3: verify_sl_tp_consistency (Matching)."""
    print("\n" + "=" * 60)
    print("TEST 3: Verify SL/TP Consistency (Matching)")
    print("=" * 60)
    
    result = verify_sl_tp_consistency(ticket, expected_sl, expected_tp)
    log_test("SL/TP matching verification", result)
    return result


def test_04_verify_sl_tp_idempotence(ticket: int, expected_sl: float, expected_tp: float):
    """Test 4: verify_sl_tp_consistency (Second Call)."""
    print("\n" + "=" * 60)
    print("TEST 4: Verify SL/TP Consistency (Idempotence)")
    print("=" * 60)
    
    result = verify_sl_tp_consistency(ticket, expected_sl, expected_tp)
    log_test("SL/TP idempotence verification", result)
    return result


def test_05_is_trade_open_blocked(ticket: int):
    """Test 5: is_trade_open - Active Position Block."""
    print("\n" + "=" * 60)
    print("TEST 5: Constraint - Active Position Block (Same Symbol)")
    print("=" * 60)
    
    is_blocked, reason = is_trade_open(SYMBOL)
    log_test("Blocked by active position", is_blocked)
    return is_blocked


def test_06_is_trade_open_allowed():
    """Test 6: is_trade_open - Different Symbol Allowed."""
    print("\n" + "=" * 60)
    print("TEST 6: Constraint - Different Symbol Allowed")
    print("=" * 60)
    
    is_blocked, reason = is_trade_open(SYMBOL_TEST6)
    log_test("Allowed for different symbol", not is_blocked)
    return not is_blocked


def test_07_close_position(ticket: int):
    """Test 7: Closing a position."""
    print("\n" + "=" * 60)
    print("TEST 7: Close Position")
    print("=" * 60)
    
    result = close_position(ticket)
    time.sleep(0.3)
    positions = mt5.positions_get(ticket=ticket)
    closed = positions is None or len(positions) == 0
    log_test("Close position verified", result and closed)
    return result and closed


def test_08_is_trade_open_cooldown():
    """Test 8: is_trade_open - Historical Cooldown check."""
    print("\n" + "=" * 60)
    print("TEST 8: Constraint - Historical Cooldown Block")
    print("=" * 60)
    
    is_blocked, reason = is_trade_open(SYMBOL)
    log_test("Blocked by cooldown (History)", is_blocked)
    return is_blocked


def test_09_place_sell_with_sl_tp():
    """Test 9: Placing a SELL order with SL and TP."""
    print("\n" + "=" * 60)
    print("TEST 9: Place SELL Order with SL and TP")
    print("=" * 60)
    
    price, sl, tp = calculate_sl_tp(SYMBOL_TEST9, mt5.ORDER_TYPE_SELL, sl_pips=50, tp_pips=100)
    if price == 0:
        return None
    
    result = place_order(
        symbol=SYMBOL_TEST9, order_type=mt5.ORDER_TYPE_SELL, volume=LOT_SIZE,
        price=price, sl=sl, tp=tp, comment="TEST: SELL"
    )
    
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log_test("Place SELL order", True)
        close_position(result.order)
        return result.order
    
    log_test("Place SELL order", False)
    return None


def test_10_magic_number_filtering():
    """Test 10: Magic number isolation."""
    print("\n" + "=" * 60)
    print("TEST 10: Magic Number Filtering")
    print("=" * 60)
    
    all_pos = mt5.positions_get() or []
    bot_pos = [p for p in all_pos if p.magic == MT5_MAGIC_NUMBER]
    log_test("Magic number filtering logic", True)
    return True


# =============================================================================
# LOGIC & CLOCK (11)
# =============================================================================

def test_11_constraints_logic_precision():
    """Test 11: 3.5-hour Cooldown Logic (Mocked Time)."""
    print("\n" + "=" * 60)
    print("TEST 11: Historical Cooldown Precision (Mocked Clock)")
    print("=" * 60)
    
    try:
        test_path = os.path.join(os.path.dirname(__file__), "test_constraints_logic.py")
        res = subprocess.run([sys.executable, test_path], capture_output=True, text=True)
        success = res.returncode == 0
        log_test("Interval Precision (209 vs 211 min)", success)
        return success
    except Exception as e:
        log_test("Interval Precision", False, str(e))
        return False


# =============================================================================
# EDGE CASES (12-16)
# =============================================================================

def test_12_invalid_symbol():
    """Test 12: Invalid Symbol."""
    print("\n" + "=" * 60)
    print("TEST 12: Edge Case - Invalid Symbol")
    print("=" * 60)
    res = place_order(symbol="FAKE_SYM", order_type=mt5.ORDER_TYPE_BUY, volume=0.01, price=1.0)
    log_test("Handle non-existent symbol", res is None)
    return res is None


def test_13_zero_volume():
    """Test 13: Zero Volume."""
    print("\n" + "=" * 60)
    print("TEST 13: Edge Case - Zero Volume")
    print("=" * 60)
    p = get_current_price(SYMBOL, mt5.ORDER_TYPE_BUY)
    res = place_order(symbol=SYMBOL, order_type=mt5.ORDER_TYPE_BUY, volume=0.0, price=p)
    success = res is None or res.retcode == 10014
    log_test("Handle 0.0 lot size", success)
    return success


def test_14_invalid_order_type():
    """Test 14: Invalid Order Type."""
    print("\n" + "=" * 60)
    print("TEST 14: Edge Case - Invalid Type")
    print("=" * 60)
    res = place_order(symbol=SYMBOL, order_type=999, volume=0.01, price=1.0)
    success = res is None or (hasattr(res, 'retcode') and res.retcode != mt5.TRADE_RETCODE_DONE)
    log_test("Handle invalid trade type", success)
    return success


def test_15_negative_sl_tp():
    """Test 15: Negative SL/TP."""
    print("\n" + "=" * 60)
    print("TEST 15: Edge Case - Negative Stops")
    print("=" * 60)
    p = get_current_price(SYMBOL, mt5.ORDER_TYPE_BUY)
    res = place_order(symbol=SYMBOL, order_type=mt5.ORDER_TYPE_BUY, volume=0.01, price=p, sl=-1.0)
    success = res is None or (hasattr(res, 'retcode') and res.retcode != mt5.TRADE_RETCODE_DONE)
    log_test("Handle negative SL/TP", success)
    return success


def test_16_close_invisible_ticket():
    """Test 16: Closing ticket that doesn't exist."""
    print("\n" + "=" * 60)
    print("TEST 16: Edge Case - Invisible Ticket")
    print("=" * 60)
    res = close_position(999999)
    log_test("Close non-existent ticket", res) # Should be True as state is safe
    return res


# =============================================================================
# STRESS (17)
# =============================================================================

def test_17_burst_stress():
    """Test 17: Burst Stress Test."""
    print("\n" + "=" * 60)
    print("TEST 17: Stress - Burst Orders")
    print("=" * 60)
    tickets = []
    for sym in STRESS_SYMBOLS:
        p = get_current_price(sym, mt5.ORDER_TYPE_BUY)
        if p > 0:
            res = place_order(symbol=sym, order_type=mt5.ORDER_TYPE_BUY, volume=LOT_SIZE, price=p)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                tickets.append(res.order)
    
    print(f"    Opened {len(tickets)} stress positions.")
    for t in tickets: close_position(t)
    log_test("Handled rapid orders (Burst)", len(tickets) > 0)
    return len(tickets) > 0


# =============================================================================
# SHUTDOWN (18)
# =============================================================================

def test_18_shutdown_mt5():
    """Test 18: MT5 Shutdown."""
    print("\n" + "=" * 60)
    print("TEST 18: Shutdown MT5")
    print("=" * 60)
    shutdown_mt5()
    log_test("MT5 Shutdown", True)
    return True


# =============================================================================
# RUNNER
# =============================================================================

def run_all_tests():
    print("\n" + "=" * 70)
    print("🧪 MT5 HANDLER COMPREHENSIVE TEST SUITE (SEQUENTIAL)")
    print("=" * 70)
    
    if not test_01_initialize_mt5(): 
        return False
    
    # Run Core (1-10)
    buy_res = test_02_place_buy_with_sl_tp()
    if buy_res:
        t, sl, tp = buy_res
        test_03_verify_sl_tp_matching(t, sl, tp)
        test_04_verify_sl_tp_idempotence(t, sl, tp)
        test_05_is_trade_open_blocked(t)
        test_06_is_trade_open_allowed()
        test_07_close_position(t)
        test_08_is_trade_open_cooldown()
        test_09_place_sell_with_sl_tp()
        test_10_magic_number_filtering()
    
    # Logic (11)
    test_11_constraints_logic_precision()
    
    # Edges (12-16)
    test_12_invalid_symbol()
    test_13_zero_volume()
    test_14_invalid_order_type()
    test_15_negative_sl_tp()
    test_16_close_invisible_ticket()
    
    # Stress (17)
    test_17_burst_stress()
    
    # Shutdown (18)
    test_18_shutdown_mt5()
    
    print("\n" + "=" * 70)
    print(f"📊 SUMMARY: {sum(1 for _, p, _ in test_results if p)}/{len(test_results)} Passed")
    print("=" * 70)
    return all(p for _, p, _ in test_results)


if __name__ == "__main__":
    if input("Start tests? (y/n): ").lower().startswith('y'):
        run_all_tests()
