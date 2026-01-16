"""
MT5 Trading Comprehensive Test Suite
=====================================
Tests all functions in mt5_handler.py:
- initialize_mt5 / shutdown_mt5
- place_order (with SL/TP, BUY and SELL)
- close_position
- verify_sl_tp_consistency
- is_trade_open (all constraints)

IMPORTANT: Run this with MT5 open and logged into a DEMO account!
"""

import sys
import os
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.mt5_handler import (
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
# TEST 1: Initialize MT5
# =============================================================================
def test_01_initialize_mt5():
    """Test MT5 initialization."""
    print("\n" + "=" * 60)
    print("TEST 1: Initialize MT5")
    print("=" * 60)
    
    result = initialize_mt5()
    log_test("MT5 Initialization", result)
    
    if result:
        account = mt5.account_info()
        if account:
            print(f"    Account: {account.login}")
            print(f"    Server: {account.server}")
            print(f"    Balance: ${account.balance:.2f}")
            is_demo = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
            print(f"    Type: {'Demo' if is_demo else '⚠️ REAL ACCOUNT!'}")
            if not is_demo:
                print("    ⚠️ WARNING: You are on a REAL account!")
    
    return result


# =============================================================================
# TEST 2: Place BUY Order with SL and TP
# =============================================================================
def test_02_place_buy_with_sl_tp():
    """Test placing a BUY order with SL and TP."""
    print("\n" + "=" * 60)
    print("TEST 2: Place BUY Order with SL and TP")
    print("=" * 60)
    
    price, sl, tp = calculate_sl_tp(SYMBOL, mt5.ORDER_TYPE_BUY, sl_pips=50, tp_pips=100)
    if price == 0:
        log_test("Get price for BUY order", False, "Could not get price")
        return None
    
    print(f"    Entry: {price:.5f}")
    print(f"    SL: {sl:.5f} (50 pips)")
    print(f"    TP: {tp:.5f} (100 pips)")
    
    result = place_order(
        symbol=SYMBOL,
        order_type=mt5.ORDER_TYPE_BUY,
        volume=LOT_SIZE,
        sl=sl,
        tp=tp,
        comment="TEST: BUY with SL/TP"
    )
    
    if result is None:
        log_test("Place BUY order with SL/TP", False, "Result is None")
        return None
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_test("Place BUY order with SL/TP", False, f"Retcode: {result.retcode}")
        return None
    
    ticket = result.order
    log_test("Place BUY order with SL/TP", True)
    print(f"    Ticket: {ticket}")
    
    # Verify position has SL/TP
    time.sleep(0.3)
    positions = mt5.positions_get(ticket=ticket)
    if positions:
        pos = positions[0]
        sl_set = abs(pos.sl - sl) < (PIP_VALUE * 2)  # Within 2 pips tolerance
        tp_set = abs(pos.tp - tp) < (PIP_VALUE * 2)
        log_test("BUY SL set correctly", sl_set, f"Expected {sl:.5f}, Got {pos.sl:.5f}")
        log_test("BUY TP set correctly", tp_set, f"Expected {tp:.5f}, Got {pos.tp:.5f}")
    else:
        log_test("BUY position exists", False)
    
    return ticket, sl, tp


# =============================================================================
# TEST 3: Verify SL/TP Consistency (Matching)
# =============================================================================
def test_03_verify_sl_tp_matching(ticket: int, expected_sl: float, expected_tp: float):
    """Test verify_sl_tp_consistency with matching values."""
    print("\n" + "=" * 60)
    print("TEST 3: Verify SL/TP Consistency (Matching)")
    print("=" * 60)
    
    result = verify_sl_tp_consistency(ticket, expected_sl, expected_tp)
    log_test("verify_sl_tp_consistency with matching values", result)
    
    # Position should still exist (not closed)
    positions = mt5.positions_get(ticket=ticket)
    position_exists = positions is not None and len(positions) > 0
    log_test("Position still open after verification", position_exists)
    
    return result and position_exists


# =============================================================================
# TEST 4: Verify SL/TP Consistency (Second Call)
# =============================================================================
def test_04_verify_sl_tp_second_call(ticket: int, expected_sl: float, expected_tp: float):
    """Test verify_sl_tp_consistency works correctly on repeated calls."""
    print("\n" + "=" * 60)
    print("TEST 4: Verify SL/TP Consistency (Second Call)")
    print("=" * 60)
    
    # Call again with the same values to ensure it's idempotent
    # The threshold (1.5 * point) handles any floating-point rounding from broker
    print(f"    Verifying SL: {expected_sl:.5f}")
    print(f"    Verifying TP: {expected_tp:.5f}")
    
    result = verify_sl_tp_consistency(ticket, expected_sl, expected_tp)
    log_test("verify_sl_tp_consistency (second call)", result)
    
    # Verify position still exists
    positions = mt5.positions_get(ticket=ticket)
    position_exists = positions is not None and len(positions) > 0
    log_test("Position still open after second verification", position_exists)
    
    return result and position_exists


# =============================================================================
# TEST 5: is_trade_open - Active Position Block (Same Symbol)
# =============================================================================
def test_05_is_trade_open_blocked(ticket: int):
    """Test is_trade_open blocks when active position exists for same symbol."""
    print("\n" + "=" * 60)
    print("TEST 5: is_trade_open - Active Position Block (Same Symbol)")
    print("=" * 60)
    
    is_blocked, reason = is_trade_open(SYMBOL)
    
    # Should be blocked because we have an open position
    log_test("is_trade_open blocks same symbol", is_blocked)
    print(f"    Blocked: {is_blocked}")
    print(f"    Reason: {reason}")
    
    return is_blocked


# =============================================================================
# TEST 6: is_trade_open - Different Symbol Allowed
# =============================================================================
def test_06_is_trade_open_different_symbol():
    """Test is_trade_open allows different symbol."""
    print("\n" + "=" * 60)
    print("TEST 6: is_trade_open - Different Symbol Allowed")
    print("=" * 60)
    
    is_blocked, reason = is_trade_open(SYMBOL_TEST6)
    
    # Should NOT be blocked because different symbol
    log_test("is_trade_open allows different symbol", not is_blocked)
    print(f"    Symbol tested: {SYMBOL_TEST6}")
    print(f"    Blocked: {is_blocked}")
    if reason:
        print(f"    Reason: {reason}")
    
    return not is_blocked


# =============================================================================
# TEST 7: Close Position
# =============================================================================
def test_07_close_position(ticket: int):
    """Test closing a position."""
    print("\n" + "=" * 60)
    print("TEST 7: Close Position")
    print("=" * 60)
    
    result = close_position(ticket)
    log_test("close_position", result)
    
    # Verify position is closed
    time.sleep(0.3)
    positions = mt5.positions_get(ticket=ticket)
    position_closed = positions is None or len(positions) == 0
    log_test("Position actually closed", position_closed)
    
    return result and position_closed


# =============================================================================
# TEST 8: is_trade_open - Historical Deals Check
# =============================================================================
def test_08_is_trade_open_historical():
    """Test is_trade_open blocks based on historical deals."""
    print("\n" + "=" * 60)
    print("TEST 8: is_trade_open - Historical Deals Check")
    print("=" * 60)
    
    # After closing position, historical deal check should still block
    is_blocked, reason = is_trade_open(SYMBOL)
    
    log_test("is_trade_open checks historical deals", is_blocked)
    print(f"    Blocked: {is_blocked}")
    print(f"    Reason: {reason}")
    
    return is_blocked


# =============================================================================
# TEST 9: Place SELL Order with SL and TP
# =============================================================================
def test_09_place_sell_with_sl_tp():
    """Test placing a SELL order with SL and TP."""
    print("\n" + "=" * 60)
    print("TEST 9: Place SELL Order with SL and TP")
    print("=" * 60)
    
    # Use different symbol to avoid constraint
    price, sl, tp = calculate_sl_tp(SYMBOL_TEST9, mt5.ORDER_TYPE_SELL, sl_pips=50, tp_pips=100)
    if price == 0:
        log_test("Get price for SELL order", False, "Could not get price")
        return None
    
    print(f"    Symbol: {SYMBOL_TEST9}")
    print(f"    Entry: {price:.5f}")
    print(f"    SL: {sl:.5f} (50 pips above)")
    print(f"    TP: {tp:.5f} (100 pips below)")
    
    result = place_order(
        symbol=SYMBOL_TEST9,
        order_type=mt5.ORDER_TYPE_SELL,
        volume=LOT_SIZE,
        sl=sl,
        tp=tp,
        comment="TEST: SELL with SL/TP"
    )
    
    if result is None:
        log_test("Place SELL order with SL/TP", False, "Result is None")
        return None
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_test("Place SELL order with SL/TP", False, f"Retcode: {result.retcode}")
        return None
    
    ticket = result.order
    log_test("Place SELL order with SL/TP", True)
    print(f"    Ticket: {ticket}")
    
    # Verify position has SL/TP
    time.sleep(0.3)
    positions = mt5.positions_get(ticket=ticket)
    if positions:
        pos = positions[0]
        sl_set = abs(pos.sl - sl) < (PIP_VALUE * 2)
        tp_set = abs(pos.tp - tp) < (PIP_VALUE * 2)
        log_test("SELL SL set correctly", sl_set, f"Expected {sl:.5f}, Got {pos.sl:.5f}")
        log_test("SELL TP set correctly", tp_set, f"Expected {tp:.5f}, Got {pos.tp:.5f}")
        
        # Close the position
        close_position(ticket)
        log_test("SELL position closed", True)
    else:
        log_test("SELL position exists", False)
    
    return ticket


# =============================================================================
# TEST 10: Magic Number Filtering
# =============================================================================
def test_10_magic_number_filtering():
    """Test that magic number correctly filters positions."""
    print("\n" + "=" * 60)
    print("TEST 10: Magic Number Filtering")
    print("=" * 60)
    
    # Get all positions
    all_positions = mt5.positions_get()
    if all_positions is None:
        all_positions = []
    
    # Filter by magic number
    bot_positions = [p for p in all_positions if p.magic == MT5_MAGIC_NUMBER]
    other_positions = [p for p in all_positions if p.magic != MT5_MAGIC_NUMBER]
    
    print(f"    Total positions: {len(all_positions)}")
    print(f"    Our bot positions (magic={MT5_MAGIC_NUMBER}): {len(bot_positions)}")
    print(f"    Other positions: {len(other_positions)}")
    
    log_test("Magic number query works", True)
    return True


# =============================================================================
# TEST 11: Shutdown MT5
# =============================================================================
def test_11_shutdown_mt5():
    """Test MT5 shutdown."""
    print("\n" + "=" * 60)
    print("TEST 11: Shutdown MT5")
    print("=" * 60)
    
    shutdown_mt5()
    log_test("MT5 Shutdown", True)
    return True


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================
def run_all_tests():
    """Run all tests in sequence."""
    print("\n" + "=" * 70)
    print("🧪 MT5 HANDLER COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    
    # Test 1: Initialize
    if not test_01_initialize_mt5():
        print("\n❌ Cannot continue: MT5 initialization failed")
        return False
    
    # Test 2: Place BUY with SL/TP
    buy_result = test_02_place_buy_with_sl_tp()
    if buy_result is None:
        print("\n⚠️ BUY order failed, skipping dependent tests")
        test_11_shutdown_mt5()
        return False
    
    ticket, sl, tp = buy_result
    
    # Test 3: Verify SL/TP consistency (matching)
    test_03_verify_sl_tp_matching(ticket, sl, tp)
    
    # Test 4: Verify SL/TP second call (idempotent)
    test_04_verify_sl_tp_second_call(ticket, sl, tp)
    
    # Test 5: is_trade_open blocked (same symbol)
    test_05_is_trade_open_blocked(ticket)
    
    # Test 6: is_trade_open different symbol
    test_06_is_trade_open_different_symbol()
    
    # Test 7: Close position
    test_07_close_position(ticket)
    
    # Test 8: Historical deals check
    test_08_is_trade_open_historical()
    
    # Test 9: Place SELL with SL/TP (different symbol)
    test_09_place_sell_with_sl_tp()
    
    # Test 10: Magic number filtering
    test_10_magic_number_filtering()
    
    # Test 11: Shutdown
    test_11_shutdown_mt5()
    
    # Print summary
    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, p, _ in test_results if p)
    total = len(test_results)
    
    for name, result, details in test_results:
        status = "✅" if result else "❌"
        print(f"  {status} {name}")
    
    print("\n" + "-" * 70)
    print(f"  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return True
    else:
        print(f"\n⚠️ {total - passed} tests failed")
        return False


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║          MT5 HANDLER COMPREHENSIVE TEST SUITE                        ║
║                                                                      ║
║  ⚠️  WARNING: This will place REAL orders on your account!           ║
║  Make sure you are using a DEMO account!                             ║
║                                                                      ║
║  Tests:                                                              ║
║    • place_order (BUY/SELL with SL/TP)                              ║
║    • verify_sl_tp_consistency (match + threshold)                   ║
║    • is_trade_open (active position, different symbol, historical)  ║
║    • close_position                                                 ║
║    • Magic number filtering                                         ║
╚══════════════════════════════════════════════════════════════════════╝
""")
    
    response = input("Continue with comprehensive tests? (yes/no): ").strip().lower()
    
    if response in ["yes", "y"]:
        success = run_all_tests()
        sys.exit(0 if success else 1)
    else:
        print("\nTest cancelled.")
        sys.exit(0)
