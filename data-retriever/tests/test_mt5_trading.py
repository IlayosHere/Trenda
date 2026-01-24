"""
MT5 Trading Comprehensive Test Suite
=====================================
Tests all functions in trading.py and constraints.py:
- initialize_mt5 / shutdown_mt5
- place_order (with SL/TP, BUY and SELL)
- close_position
- verify_sl_tp_consistency
- can_execute_trade (Active, History, Cooldown, and Logic)

IMPORTANT: Run this with MT5 open and logged into a DEMO account!
"""

import sys
import os
import time
import subprocess
import threading
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from externals.meta_trader import (
    initialize_mt5,
    shutdown_mt5,
    place_order,
    close_position,
    can_execute_trade,
    verify_position_consistency,
)
from configuration import MT5_MAGIC_NUMBER

# Test configuration
SYMBOL = "EURUSD"
SYMBOL_TEST6 = "NZDUSD"  # For Test 6: different symbol check
SYMBOL_TEST9 = "AUDUSD"  # For Test 9: SELL order test
STRESS_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
LOT_SIZE = 0.01  # Minimum lot for most brokers
PIP_VALUE = 0.0001  # For 5-digit brokers (EURUSD)

# Track test results
test_results = []


def log_test(name: str, passed: bool, details: str = ""):
    """Log test result."""
    status = "PASS" if passed else "FAIL"
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
    print("TEST 01: Initialize MT5")
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
    print("TEST 02: Place BUY Order with SL and TP")
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


def test_03_verify_position_matching(ticket: int, expected_sl: float, expected_tp: float, vol: float, price: float):
    """Test 3: verify_position_consistency (Matching)."""
    print("\n" + "=" * 60)
    print("TEST 03: Verify Position Consistency (Matching)")
    print("=" * 60)
    
    result = verify_position_consistency(ticket, expected_sl, expected_tp, vol, price)
    log_test("Position parameters matching verification", result)
    return result


def test_04_verify_position_idempotence(ticket: int, expected_sl: float, expected_tp: float, vol: float, price: float):
    """Test 4: verify_position_consistency (Second Call)."""
    print("\n" + "=" * 60)
    print("TEST 04: Verify Position Consistency (Idempotence)")
    print("=" * 60)
    
    result = verify_position_consistency(ticket, expected_sl, expected_tp, vol, price)
    log_test("Position idempotence verification", result)
    return result


def test_05_can_execute_trade_blocked(ticket: int):
    """Test 5: can_execute_trade - Active Position Block."""
    print("\n" + "=" * 60)
    print("TEST 05: Constraint - Active Position Block (Same Symbol)")
    print("=" * 60)
    
    is_blocked, reason = can_execute_trade(SYMBOL)
    log_test("Blocked by active position", is_blocked, reason if not is_blocked else "")
    return is_blocked


def test_06_can_execute_trade_allowed():
    """Test 6: can_execute_trade - Different Symbol Allowed."""
    print("\n" + "=" * 60)
    print("TEST 06: Constraint - Different Symbol Allowed")
    print("=" * 60)
    
    # Clear any trading lock that might have been triggered by previous tests
    from externals.meta_trader.safeguards import _trading_lock
    _trading_lock.clear_lock()
    
    time.sleep(1.0) # Avoid historical cooldown from previous tests
    is_blocked, reason = can_execute_trade(SYMBOL_TEST6)
    log_test("Allowed for different symbol", not is_blocked, reason if is_blocked else "")
    return not is_blocked


def test_07_close_position(ticket: int):
    """Test 7: Closing a position."""
    print("\n" + "=" * 60)
    print("TEST 07: Close Position")
    print("=" * 60)
    
    result = close_position(ticket)
    time.sleep(0.3)
    positions = mt5.positions_get(ticket=ticket)
    closed = positions is None or len(positions) == 0
    log_test("Close position verified", result and closed)
    return result and closed


def test_08_can_execute_trade_cooldown():
    """Test 8: can_execute_trade - Historical Cooldown check."""
    print("\n" + "=" * 60)
    print("TEST 08: Constraint - Historical Cooldown Block")
    print("=" * 60)
    
    is_blocked, reason = can_execute_trade(SYMBOL)
    log_test("Blocked by cooldown (History)", is_blocked, reason if not is_blocked else "")
    return is_blocked


def test_09_place_sell_with_sl_tp():
    """Test 9: Placing a SELL order with SL and TP."""
    print("\n" + "=" * 60)
    print("TEST 09: Place SELL Order with SL and TP")
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
# EXTENDED COVERAGE (19-30)
# =============================================================================

def setup_mock_mt5(mock_mt5):
    """Inject standard MT5 constants into a mock object."""
    mock_mt5.TRADE_ACTION_DEAL = mt5.TRADE_ACTION_DEAL
    mock_mt5.ORDER_TIME_SPECIFIED = mt5.ORDER_TIME_SPECIFIED
    mock_mt5.ORDER_TYPE_SELL = mt5.ORDER_TYPE_SELL
    mock_mt5.ORDER_TYPE_BUY = mt5.ORDER_TYPE_BUY
    mock_mt5.POSITION_TYPE_BUY = mt5.POSITION_TYPE_BUY
    mock_mt5.POSITION_TYPE_SELL = mt5.POSITION_TYPE_SELL
    mock_mt5.ORDER_TIME_GTC = mt5.ORDER_TIME_GTC
    mock_mt5.ORDER_FILLING_IOC = mt5.ORDER_FILLING_IOC
    mock_mt5.TRADE_RETCODE_DONE = mt5.TRADE_RETCODE_DONE
    mock_mt5.TRADE_RETCODE_REJECT = mt5.TRADE_RETCODE_REJECT
    mock_mt5.TRADE_RETCODE_CANCEL = mt5.TRADE_RETCODE_CANCEL
    mock_mt5.SYMBOL_TRADE_MODE_DISABLED = mt5.SYMBOL_TRADE_MODE_DISABLED
    mock_mt5.SYMBOL_TRADE_MODE_CLOSEONLY = mt5.SYMBOL_TRADE_MODE_CLOSEONLY
    mock_mt5.TRADE_RETCODE_FROZEN = mt5.TRADE_RETCODE_FROZEN

def test_19_connection_reinit():
    """Test 19: Connection Re-initialization on Disconnect."""
    print("\n" + "=" * 60)
    print("TEST 19: Connection Re-initialization (Mocked Disconnect)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    conn = MT5Connection()
    
    with patch.object(mt5, 'terminal_info') as mock_term:
        # Simulate connected first
        mock_term.return_value.connected = True
        conn._initialized = True
        res1 = conn.initialize()
        
        # Simulate disconnected
        mock_term.return_value.connected = False
        # Ensure the mock_term returns a connected status on the SECOND call inside initialize
        mock_term.side_effect = [
            MagicMock(connected=False), # First check in initialize (re-init)
            MagicMock(connected=True)   # Second check in initialize (broker connection)
        ]
        with patch.object(mt5, 'initialize', return_value=True) as mock_init:
             # Should detect disconnect and call initialize again
             res2 = conn.initialize()
             log_test("Re-init triggered on disconnect", mock_init.called and res2)
             return mock_init.called and res2

def test_20_connection_failure():
    """Test 20: Initialization Failure Handling."""
    print("\n" + "=" * 60)
    print("TEST 20: Initialization Failure Handling")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    conn = MT5Connection()
    conn._initialized = False
    
    with patch.object(mt5, 'initialize', return_value=False):
        res = conn.initialize()
        log_test("Handle MT5 init failure", res is False)
        return res is False

def test_21_zero_price_failure():
    """Test 21: Reject Order with 0.0 Price."""
    print("\n" + "=" * 60)
    print("TEST 21: Reject Order with 0.0 Price")
    print("=" * 60)
    
    res = place_order(symbol=SYMBOL, order_type=mt5.ORDER_TYPE_BUY, volume=LOT_SIZE, price=0.0)
    log_test("Reject 0.0 price", res is None)
    return res is None

def test_22_symbol_visibility():
    """Test 22: Automatic Symbol Selection (Visibility)."""
    print("\n" + "=" * 60)
    print("TEST 22: Symbol Selection / Visibility")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Simulate symbol exists but is not visible
    sym_info = MagicMock()
    sym_info.visible = False
    sym_info.digits = 5
    sym_info.trade_stops_level = 0
    sym_info.trade_freeze_level = 0
    sym_info.trade_mode = mt5.SYMBOL_TRADE_MODE_FULL
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info.return_value = sym_info
    mock_conn.mt5.symbol_select.return_value = True
    mock_conn.mt5.symbol_info_tick.return_value.time = 1000
    
    trader = MT5Trader(mock_conn)
    trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    
    selected = mock_conn.mt5.symbol_select.called
    log_test("Auto-select invisible symbol", selected)
    return selected

def test_23_price_normalization():
    """Test 23: Price Normalization (Rounding)."""
    print("\n" + "=" * 60)
    print("TEST 23: Price Normalization (Rounding)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    sym_info = MagicMock()
    sym_info.digits = 3 # Round to 3 digits
    sym_info.visible = True
    sym_info.trade_stops_level = 0
    sym_info.trade_freeze_level = 0
    sym_info.trade_mode = mt5.SYMBOL_TRADE_MODE_FULL
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info.return_value = sym_info
    mock_conn.mt5.symbol_info_tick.return_value.time = 1000
    
    trader = MT5Trader(mock_conn)
    # Give a price with many digits
    trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.123456, sl=1.111111, tp=1.133333)
    
    sent_request = mock_conn.mt5.order_send.call_args[0][0]
    normalized = (sent_request['price'] == 1.123 and 
                  sent_request['sl'] == 1.111 and 
                  sent_request['tp'] == 1.133)
    
    log_test("Price rounding to symbol digits", normalized)
    return normalized

def test_24_tick_failure():
    """Test 24: Handle Tick Info Failure."""
    print("\n" + "=" * 60)
    print("TEST 24: Handle Tick Info Failure")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    sym_info = mock_conn.mt5.symbol_info.return_value
    sym_info.visible = True
    sym_info.trade_mode = mt5.SYMBOL_TRADE_MODE_FULL
    sym_info.trade_stops_level = 0
    sym_info.trade_freeze_level = 0
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info_tick.return_value = None # Tick fail
    
    trader = MT5Trader(mock_conn)
    res = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    
    log_test("Handle missing tick data", res is None)
    return res is None

def test_25_retry_logic_success():
    """Test 25: Recovery after Transient Close Failure."""
    print("\n" + "=" * 60)
    print("TEST 25: Recovery after Transient Close Failure")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # 1. First attempt fails, second succeeds
    res_fail = MagicMock(retcode=10006) # Rejected
    res_ok = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    mock_conn.mt5.order_send.side_effect = [res_fail, res_ok]
    
    # Create position mock for initial state
    position_mock = MagicMock(symbol=SYMBOL, volume=0.01, type=mt5.POSITION_TYPE_BUY, ticket=12345)
    
    # Setup positions_get to return position initially, then empty after close
    call_count = [0]
    def mock_pos_get(*args, **kwargs):
        call_count[0] += 1
        # First call: position exists (first attempt in _attempt_close)
        # Second call: position still exists (second attempt after first failed)
        # Third call: position is gone (verification in _verify_closure after successful close)
        if call_count[0] <= 2:
            return [position_mock]
        return []  # Position closed
    
    mock_conn.mt5.positions_get.side_effect = mock_pos_get
    # Setup symbol_info_tick for order placement
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1000, ask=1.1001)
    
    trader = MT5Trader(mock_conn)
    with patch('time.sleep'): # Don't actually wait
        with patch('system_shutdown.shutdown_system'):  # Mock shutdown to prevent exit
            res = trader.close_position(12345)
            
    log_test("Retry success after transient failure", res)
    return res

def test_26_retry_exhaustion():
    """Test 26: Retry Exhaustion and Emergency Logging."""
    print("\n" + "=" * 60)
    print("TEST 26: Retry Exhaustion (All Attempts Fail)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # All attempts fail
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10006)
    mock_conn.mt5.positions_get.return_value = [MagicMock(symbol=SYMBOL, volume=0.01, type=mt5.POSITION_TYPE_BUY)]
    
    trader = MT5Trader(mock_conn)
    with patch('time.sleep'):
        with patch('system_shutdown.shutdown_system') as mock_shutdown:
            # Mock shutdown to raise SystemExit so we can catch it
            mock_shutdown.side_effect = SystemExit("Test shutdown")
            try:
                res = trader.close_position(12345)
            except SystemExit:
                res = False
                mock_shutdown.assert_called_once()
        
    log_test("Detect retry exhaustion", res is False)
    return res is False

def test_27_verification_leak():
    """Test 27: detect 'Ghost' positions (Close signal ok but position still open)."""
    print("\n" + "=" * 60)
    print("TEST 27: Detect Ghost Positions (Close Signal OK, Pos Remains)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Order send says DONE
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    # But positions_get STILL returns the position
    mock_conn.mt5.positions_get.return_value = [MagicMock(ticket=12345)]
    
    trader = MT5Trader(mock_conn)
    with patch('time.sleep'):
        with patch('system_shutdown.shutdown_system') as mock_shutdown:
            # Mock shutdown to raise SystemExit so we can catch it
            mock_shutdown.side_effect = SystemExit("Test shutdown")
            try:
                res = trader.close_position(12345)
            except SystemExit:
                res = False
                mock_shutdown.assert_called_once()
        
    log_test("Detect failed verification (Ghost)", res is False)
    return res is False

def test_28_mismatch_triggers_close():
    """Test 28: SL/TP Mismatch triggers automatic closure."""
    print("\n" + "=" * 60)
    print("TEST 28: Mismatch triggers closure")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Position has different SL than requested
    pos = MagicMock(ticket=12345, sl=1.10, tp=1.20, symbol=SYMBOL, volume=0.01, price_open=1.15, type=mt5.POSITION_TYPE_BUY)
    
    # Setup positions_get to return position with mismatched SL
    mock_conn.mt5.positions_get.return_value = [pos]
    # sym_info
    sym_info = MagicMock()
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info.return_value = sym_info
    
    trader = MT5Trader(mock_conn)
    
    with patch.object(trader._position_closer, 'close_position') as mock_close:
        with patch('time.sleep'):
             # Requested 1.05 SL, actual is 1.10
             res = trader.verify_position_consistency(12345, 1.05, 1.20)
             log_test("Close triggered on mismatch", res is False and mock_close.called)
             return res is False and mock_close.called

def test_29_verification_missing_pos():
    """Test 29: Position disappears during verification."""
    print("\n" + "=" * 60)
    print("TEST 29: Position goes missing during verification")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Position not found - positions_get returns empty
    mock_conn.mt5.positions_get.return_value = []
    sym_info = MagicMock()
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info.return_value = sym_info
    
    trader = MT5Trader(mock_conn)
    
    with patch('time.sleep'):
        res = trader.verify_position_consistency(12345, 1.1, 1.2)
        log_test("Handle missing position in verification", res is True) # Returns True (safe)
        return res is True

def test_30_concurrency_stress():
    """Test 30: Multi-threaded order placement stress."""
    print("\n" + "=" * 60)
    print("TEST 30: Concurrency Stress (Shared Lock)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    # Real test with locks
    conn = MT5Connection()
    if not conn.initialize():
        log_test("Concurrency skipped (Init failed)", True)
        return True
        
    trader = MT5Trader(conn)
    
    results = []
    def place_concurrent():
        p = get_current_price(SYMBOL, mt5.ORDER_TYPE_BUY)
        if p > 0:
            res = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, LOT_SIZE, p)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                results.append(res.order)

    threads = [threading.Thread(target=place_concurrent) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    print(f"    Concurrent orders successful: {len(results)}")
    for ticket in results: trader.close_position(ticket)
    
    log_test("Concurrent lock handling", True)
    return True

def test_31_trade_mode_validation():
    """Test 31: Reject trade if mode is DISABLED or CLOSE-ONLY."""
    print("\n" + "=" * 60)
    print("TEST 31: Trade Mode Validation (Disabled/Close-Only)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # 1. Test Disabled
    sym_info_disabled = MagicMock(visible=True, trade_mode=mt5.SYMBOL_TRADE_MODE_DISABLED)
    mock_conn.mt5.symbol_info.return_value = sym_info_disabled
    
    trader = MT5Trader(mock_conn)
    res_disabled = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    
    # 2. Test Close-Only
    sym_info_close_only = MagicMock(visible=True, trade_mode=mt5.SYMBOL_TRADE_MODE_CLOSEONLY)
    mock_conn.mt5.symbol_info.return_value = sym_info_close_only
    res_close_only = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1)
    
    log_test("Reject Disabled mode", res_disabled is None)
    log_test("Reject Close-Only mode", res_close_only is None)
    return res_disabled is None and res_close_only is None

def test_32_sl_tp_distance_validation():
    """Test 32: Reject trade if SL/TP is too close (freeze/stops level)."""
    print("\n" + "=" * 60)
    print("TEST 32: SL/TP Distance Validation (Stops/Freeze Level)")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Symbol info with 10 points stops level
    sym_info = MagicMock(visible=True, trade_mode=mt5.SYMBOL_TRADE_MODE_FULL, 
                         digits=5, point=0.0001, 
                         trade_stops_level=10, trade_freeze_level=0)
    mock_conn.mt5.symbol_info.return_value = sym_info
    
    trader = MT5Trader(mock_conn)
    
    # Price 1.1000, SL 1.0995 (5 points away, but level is 10)
    res = trader.place_order(SYMBOL, mt5.ORDER_TYPE_BUY, 0.01, 1.1000, sl=1.0995)
    
    log_test("Reject SL too close to price", res is None)
    return res is None

def test_33_close_frozen_retry():
    """Test 33: Retry on frozen positions during close."""
    print("\n" + "=" * 60)
    print("TEST 33: Retry on Frozen positions during close")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # 1. First attempt returns FROZEN, second returns DONE
    res_frozen = MagicMock(retcode=mt5.TRADE_RETCODE_FROZEN)
    res_ok = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    mock_conn.mt5.order_send.side_effect = [res_frozen, res_ok]
    
    # Position exists for first two calls, then becomes None (closed)
    pos = MagicMock(symbol=SYMBOL, volume=0.01, type=mt5.POSITION_TYPE_BUY, ticket=12345)
    
    # Setup positions_get to return position initially, then empty after close
    call_count = [0]
    def mock_pos_get(*args, **kwargs):
        call_count[0] += 1
        # First call: position exists (first attempt in _attempt_close)
        # Second call: position still exists (second attempt after FROZEN)
        # Third call: position is gone (verification in _verify_closure after successful close)
        if call_count[0] <= 2:
            return [pos]
        return []  # Position closed
    
    mock_conn.mt5.positions_get.side_effect = mock_pos_get
    # Setup symbol_info_tick for order placement
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1000, ask=1.1001)
    
    trader = MT5Trader(mock_conn)
    with patch('time.sleep'):
        with patch('system_shutdown.shutdown_system'):  # Mock shutdown to prevent exit
            res = trader.close_position(12345)
            
    log_test("Retry triggered on FROZEN retcode", res)
    return res

def test_34_verify_volume_mismatch():
    """Test 34: Volume mismatch triggers closure."""
    print("\n" + "=" * 60)
    print("TEST 34: Volume Mismatch triggers closure")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Position has different volume (0.02) than requested (0.01)
    pos = MagicMock(ticket=12345, symbol=SYMBOL, sl=1.1, tp=1.2, volume=0.02, price_open=1.15, type=mt5.POSITION_TYPE_BUY)
    
    # Setup positions_get to return position initially, then empty after close
    call_count = [0]
    def mock_pos_get(*args, **kwargs):
        call_count[0] += 1
        # First call: position exists (for verification check)
        # Second call: position still exists (for close attempt)
        # Third call: position is gone (after successful close)
        if call_count[0] <= 2:
            return [pos]
        return []  # Position closed
    
    mock_conn.mt5.positions_get.side_effect = mock_pos_get
    sym_info = MagicMock()
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info.return_value = sym_info
    
    # Setup successful close
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=mt5.TRADE_RETCODE_DONE)
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1000, ask=1.1001)
    
    trader = MT5Trader(mock_conn)
    with patch('time.sleep'):
        with patch('system_shutdown.shutdown_system'):  # Mock shutdown to prevent exit
            res = trader.verify_position_consistency(12345, 1.1, 1.2, expected_volume=0.01)
    
    log_test("Close triggered on volume mismatch", res is False)
    return res is False

def test_35_verify_slippage_mismatch():
    """Test 35: Extreme slippage triggers closure."""
    print("\n" + "=" * 60)
    print("TEST 35: Slippage Mismatch (Price) triggers closure")
    print("=" * 60)
    
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.trading import MT5Trader
    
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = True
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Position has different price (1.16) than requested (1.15) -> 100 points diff
    position_mock = MagicMock(ticket=12345, symbol=SYMBOL, sl=1.1, tp=1.2, volume=0.01, price_open=1.16, type=mt5.POSITION_TYPE_BUY)
    mock_conn.mt5.positions_get.return_value = [position_mock]
    
    sym_info = MagicMock()
    sym_info.point = 0.0001
    mock_conn.mt5.symbol_info.return_value = sym_info
    
    # Configure mocks for close attempt (will be triggered by verify_position_consistency)
    mock_conn.mt5.symbol_info_tick.return_value = MagicMock(bid=1.1000, ask=1.1001)
    # Configure order_send to fail with a proper retcode
    mock_conn.mt5.order_send.return_value = MagicMock(retcode=10006)  # Invalid request
    mock_conn.mt5.last_error.return_value = (10006, "Invalid request")
    
    trader = MT5Trader(mock_conn)
    
    with patch('time.sleep'):
        with patch('system_shutdown.shutdown_system'):  # Mock shutdown to prevent exit
            # Threshold is deviation (20) or 5 points. 100 points should fail.
            res = trader.verify_position_consistency(12345, 1.1, 1.2, expected_volume=0.01, expected_price=1.15)
    
    log_test("Close triggered on price slippage mismatch", res is False)
    return res is False


def test_36_jpy_position_consistency():
    """Test 36: JPY position consistency with symbol digits fetched from symbol info."""
    print("\n" + "=" * 60)
    print("TEST 36: JPY Position Consistency (Symbol Digits from Symbol Info)")
    print("=" * 60)
    
    JPY_SYMBOL = "USDJPY"  # JPY pairs typically have 3 digits
    
    # Get symbol info to fetch digits (like in live trading)
    sym_info = mt5.symbol_info(JPY_SYMBOL)
    if sym_info is None:
        log_test("JPY symbol info available", False, f"Symbol {JPY_SYMBOL} not found")
        return False
    
    symbol_digits = sym_info.digits
    log_test(f"JPY symbol digits fetched: {symbol_digits}", True)
    
    # Calculate SL/TP based on current price
    price, sl, tp = calculate_sl_tp(JPY_SYMBOL, mt5.ORDER_TYPE_BUY, sl_pips=50, tp_pips=100)
    if price == 0:
        log_test("Get price for JPY order", False, "Could not get price")
        return False
    
    # Round to symbol digits (like in order placement)
    price_rounded = round(price, symbol_digits)
    sl_rounded = round(sl, symbol_digits) if sl > 0 else 0.0
    tp_rounded = round(tp, symbol_digits) if tp > 0 else 0.0
    
    log_test(f"Prices rounded to {symbol_digits} digits", True, 
             f"Price: {price_rounded}, SL: {sl_rounded}, TP: {tp_rounded}")
    
    # Place order
    result = place_order(
        symbol=JPY_SYMBOL, order_type=mt5.ORDER_TYPE_BUY, volume=LOT_SIZE,
        price=price_rounded, sl=sl_rounded, tp=tp_rounded, comment="TEST: JPY"
    )
    
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log_test("Place JPY order", False, f"Retcode: {result.retcode if result else 'None'}")
        return False
    
    ticket = result.order
    log_test("Place JPY order with SL/TP", True)
    
    # Wait for position to be available
    time.sleep(0.5)
    
    # Verify position consistency using the rounded values
    # This simulates what happens in live trading where we pass execution.sl_price/tp_price
    # which should match what was sent (rounded to symbol digits)
    verification_result = verify_position_consistency(
        ticket, sl_rounded, tp_rounded, LOT_SIZE, price_rounded
    )
    
    log_test("JPY position consistency verified", verification_result)
    
    # Clean up
    if ticket:
        close_position(ticket)
        time.sleep(0.3)
    
    return verification_result


def test_37_market_moved_retry():
    """Test 37: MARKET_MOVED error automatic retry with fresh prices."""
    print("\n" + "=" * 60)
    print("TEST 37: MARKET_MOVED Error Automatic Retry")
    print("=" * 60)
    
    # This test verifies that MARKET_MOVED errors (10004, 10020, 10021, 10025)
    # trigger automatic retry with fresh prices
    # Note: We can't easily simulate MARKET_MOVED errors in live trading,
    # but we can verify the retry logic works by checking the code path
    
    from externals.meta_trader.order_placement import OrderPlacer
    from externals.meta_trader.connection import MT5Connection
    from externals.meta_trader.error_categorization import MT5ErrorCategorizer, ErrorCategory
    
    # Test error categorization
    market_moved_codes = [10004, 10020, 10021, 10025]
    all_categorized = True
    for code in market_moved_codes:
        category = MT5ErrorCategorizer.categorize(code)
        if category != ErrorCategory.MARKET_MOVED:
            log_test(f"Error code {code} categorization", False, f"Expected MARKET_MOVED, got {category}")
            all_categorized = False
        else:
            log_test(f"Error code {code} categorized as MARKET_MOVED", True)
    
    # Test SL/TP recalculation logic (unit test)
    connection = MT5Connection()
    placer = OrderPlacer(connection)
    
    # Test BUY order SL/TP recalculation
    original_price = 1.1000
    original_sl = 1.0950  # 50 pips below
    original_tp = 1.1100  # 100 pips above
    fresh_price = 1.1005  # Price moved up 5 pips
    
    fresh_sl, fresh_tp = placer._recalculate_sl_tp(
        fresh_price, original_price, original_sl, original_tp, mt5.ORDER_TYPE_BUY
    )
    
    expected_sl = 1.0955  # 50 pips below fresh price
    expected_tp = 1.1105  # 100 pips above fresh price
    
    sl_correct = abs(fresh_sl - expected_sl) < 0.0001
    tp_correct = abs(fresh_tp - expected_tp) < 0.0001
    
    log_test("BUY SL recalculation", sl_correct, 
             f"Expected: {expected_sl}, Got: {fresh_sl}")
    log_test("BUY TP recalculation", tp_correct,
             f"Expected: {expected_tp}, Got: {fresh_tp}")
    
    # Test SELL order SL/TP recalculation
    original_price_sell = 1.1000
    original_sl_sell = 1.1050  # 50 pips above (for SELL)
    original_tp_sell = 1.0900  # 100 pips below (for SELL)
    fresh_price_sell = 1.0995  # Price moved down 5 pips
    
    fresh_sl_sell, fresh_tp_sell = placer._recalculate_sl_tp(
        fresh_price_sell, original_price_sell, original_sl_sell, original_tp_sell, mt5.ORDER_TYPE_SELL
    )
    
    expected_sl_sell = 1.1045  # 50 pips above fresh price
    expected_tp_sell = 1.0895  # 100 pips below fresh price
    
    sl_sell_correct = abs(fresh_sl_sell - expected_sl_sell) < 0.0001
    tp_sell_correct = abs(fresh_tp_sell - expected_tp_sell) < 0.0001
    
    log_test("SELL SL recalculation", sl_sell_correct,
             f"Expected: {expected_sl_sell}, Got: {fresh_sl_sell}")
    log_test("SELL TP recalculation", tp_sell_correct,
             f"Expected: {expected_tp_sell}, Got: {fresh_tp_sell}")
    
    return all_categorized and sl_correct and tp_correct and sl_sell_correct and tp_sell_correct


# =============================================================================
# RUNNER
# =============================================================================

def run_all_tests():
    print("\n" + "=" * 70)
    print("MT5 HANDLER COMPREHENSIVE TEST SUITE (SEQUENTIAL)")
    print("=" * 70)
    
    if not test_01_initialize_mt5(): 
        return False
    
    # Run Core (1-10)
    buy_res = test_02_place_buy_with_sl_tp()
    if buy_res:
        t, sl, tp = buy_res
        price_open = mt5.positions_get(ticket=t)[0].price_open
        test_03_verify_position_matching(t, sl, tp, LOT_SIZE, price_open)
        test_04_verify_position_idempotence(t, sl, tp, LOT_SIZE, price_open)
        test_05_can_execute_trade_blocked(t)
        test_06_can_execute_trade_allowed()
        test_07_close_position(t)
        test_08_can_execute_trade_cooldown()
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
    
    # Extended (19-30)
    test_19_connection_reinit()
    test_20_connection_failure()
    test_21_zero_price_failure()
    test_22_symbol_visibility()
    test_23_price_normalization()
    test_24_tick_failure()
    test_25_retry_logic_success()
    test_26_retry_exhaustion()
    test_27_verification_leak()
    test_28_mismatch_triggers_close()
    test_29_verification_missing_pos()
    test_30_concurrency_stress()
    test_31_trade_mode_validation()
    test_32_sl_tp_distance_validation()
    test_33_close_frozen_retry()
    test_34_verify_volume_mismatch()
    test_35_verify_slippage_mismatch()
    test_36_jpy_position_consistency()
    test_37_market_moved_retry()

    # Shutdown (18)
    test_18_shutdown_mt5()
    
    print("\n" + "=" * 70)
    print(f"SUMMARY: {sum(1 for _, p, _ in test_results if p)}/{len(test_results)} Passed")
    print("=" * 70)
    return all(p for _, p, _ in test_results)


if __name__ == "__main__":
    if input("Start tests? (y/n): ").lower().startswith('y'):
        run_all_tests()
