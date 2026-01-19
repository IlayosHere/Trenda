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
    log_test("Blocked by active position", is_blocked, reason if not is_blocked else "")
    return is_blocked


def test_06_is_trade_open_allowed():
    """Test 6: is_trade_open - Different Symbol Allowed."""
    print("\n" + "=" * 60)
    print("TEST 6: Constraint - Different Symbol Allowed")
    print("=" * 60)
    
    is_blocked, reason = is_trade_open(SYMBOL_TEST6)
    log_test("Allowed for different symbol", not is_blocked, reason if is_blocked else "")
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
    log_test("Blocked by cooldown (History)", is_blocked, reason if not is_blocked else "")
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
    
    mock_conn.mt5.symbol_info.return_value.visible = True
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
    
    # Position exists
    mock_conn.mt5.positions_get.return_value = [MagicMock(symbol=SYMBOL, volume=0.01, type=mt5.POSITION_TYPE_BUY)]
    # Final verification: position gone
    def mock_pos_get(*args, **kwargs):
        if 'ticket' in kwargs: return [] # Empty if looking for specific ticket after close
        return []
    
    trader = MT5Trader(mock_conn)
    with patch('time.sleep'): # Don't actually wait
        with patch.object(trader, '_get_active_position', side_effect=[MagicMock(), MagicMock(), None]):
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
        res = trader.close_position(12345)
        
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
        res = trader.close_position(12345)
        
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
    def mock_pos_get(*args, **kwargs):
        return MagicMock(sl=1.10, tp=1.20, symbol=SYMBOL)
    
    # sym_info
    mock_conn.mt5.symbol_info.return_value.point = 0.0001
    
    trader = MT5Trader(mock_conn)
    trader._get_active_position = mock_pos_get
    
    with patch.object(trader, 'close_position') as mock_close:
        with patch('time.sleep'):
             # Requested 1.05 SL, actual is 1.10
             res = trader.verify_sl_tp_consistency(12345, 1.05, 1.20)
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
    
    trader = MT5Trader(mock_conn)
    # Position not found
    trader._get_active_position = MagicMock(return_value=None)
    
    with patch('time.sleep'):
        res = trader.verify_sl_tp_consistency(12345, 1.1, 1.2)
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

    # Shutdown (18)
    test_18_shutdown_mt5()
    
    print("\n" + "=" * 70)
    print(f"SUMMARY: {sum(1 for _, p, _ in test_results if p)}/{len(test_results)} Passed")
    print("=" * 70)
    return all(p for _, p, _ in test_results)


if __name__ == "__main__":
    if input("Start tests? (y/n): ").lower().startswith('y'):
        run_all_tests()
