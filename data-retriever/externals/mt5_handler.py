import time
import threading
from datetime import datetime, timedelta
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from configuration import MT5_MAGIC_NUMBER, MT5_DEVIATION, MT5_EXPIRATION_MINUTES, MT5_MAX_ACTIVE_TRADES, MT5_MIN_TRADE_INTERVAL_HOURS
from logger import get_logger

logger = get_logger(__name__)

# Flag to track if MT5 has been initialized in this session
_mt5_initialized = False
# Lock to serialize MT5 API calls (MT5 is not thread-safe)
mt5_lock = threading.Lock()

def initialize_mt5():
    """Initializes and checks the MT5 connection only once per session."""
    global _mt5_initialized
    
    if mt5 is None:
        logger.warning("MetaTrader5 package not found. Skipping initialization.")
        return False
        
    with mt5_lock:
        if _mt5_initialized:
            return True

        if not mt5.initialize():
            logger.error(f"MT5 initialization failed. Error: {mt5.last_error()}")
            return False
        
        logger.info("✅ MT5 initialized successfully.")
        _mt5_initialized = True
        return True

def shutdown_mt5():
    """Shuts down the MT5 connection and resets state."""
    global _mt5_initialized
    if mt5 is not None:
        logger.info("Shutting down MT5 connection...")
        mt5.shutdown()
    _mt5_initialized = False

def place_order(symbol: str, order_type: int, volume: float, price: float = 0.0, sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, magic: int = MT5_MAGIC_NUMBER, comment: str = "", expiration_minutes: int = MT5_EXPIRATION_MINUTES):
    """
    Unified function to place any type of order in MT5 with automatic 10-minute expiration.
    
    Args:
        symbol: The trading instrument (e.g., "EURUSD").
        order_type: Direction (mt5.ORDER_TYPE_BUY/SELL) or Pending (mt5.ORDER_TYPE_BUY_LIMIT/STOP, etc.).
        price: The price for pending orders. If 0.0, it uses current market price for direct deals.
        volume: Order size in lots.
        sl: Stop loss price.
        tp: Take profit price.
        deviation: Max allowed slippage (points).
        magic: Unique identifier for the EA/bot (default from config).
        comment: Personal note.
        expiration_minutes: Minutes after which the order is canceled if not filled (default 10).
    """
    if not initialize_mt5():
        return None

    # 1. Ensure symbol is visible and select it
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error(f"Symbol {symbol} not found.")
        return None
    
    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            logger.error(f"Failed to select symbol {symbol}.")
            return None

    # 2. Get current price
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"Failed to get tick info for {symbol}. Error: {mt5.last_error()}")
        return None

    if price == 0.0:
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    # 3. Normalize prices (Round to symbol's digits)
    price = round(price, symbol_info.digits)
    sl = round(sl, symbol_info.digits) if sl > 0 else 0.0
    tp = round(tp, symbol_info.digits) if tp > 0 else 0.0

    # 4. Calculate expiration timestamp (Server time + minutes)
    expiration_time = int(tick.time + (expiration_minutes * 60))

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_SPECIFIED,
        "expiration": expiration_time,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    with mt5_lock:
        result = mt5.order_send(request)
    
    if result is None:
        logger.error(f"Order send failed for {symbol}. Result is None.")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed for {symbol}. Action: {mt5.TRADE_ACTION_DEAL}, Retcode: {result.retcode}, Error: {mt5.last_error()}")
        return result

    # 5. Success Logging
    logger.info(f"✅ Success: Order placed - sym:{symbol}, vol:{volume}, type:{order_type}, price:{price}, ticket:{result.order}")
    
    return result


def close_position(ticket: int) -> bool:
    """
    Closes an active position by its ticket ID.
    
    Args:
        ticket: The position ticket ID.
        
    Returns:
        True if successfully closed, False otherwise.
    """
    if not initialize_mt5():
        return False

    with mt5_lock:
        positions = mt5.positions_get(ticket=ticket)
    if not positions:
        logger.error(f"❌ Failed to close position {ticket}: Position not found.")
        return False
    
    position = positions[0]
    symbol = position.symbol
    volume = position.volume
    
    # Correcting logic: 
    # To close a BUY position (type 0), we SELL (type 1) at the Bid price.
    # To close a SELL position (type 1), we BUY (type 0) at the Ask price.
    if position.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        with mt5_lock:
            tick = mt5.symbol_info_tick(symbol)
            price = tick.bid if tick else None
    else:
        order_type = mt5.ORDER_TYPE_BUY
        with mt5_lock:
            tick = mt5.symbol_info_tick(symbol)
            price = tick.ask if tick else None

    if not price:
        logger.error(f"❌ Failed to close position {ticket}: Failed to get current price for {symbol}.")
        return False
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "position": ticket, # Important: specify the position to close
        "price": price,
        "deviation": MT5_DEVIATION,
        "magic": MT5_MAGIC_NUMBER,
        "comment": "Auto-close: SL/TP mismatch",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = mt5.last_error() if mt5 else "Unknown"
        logger.error(f"❌ Failed to close position {ticket}. Result: {result.retcode if result else 'None'}, Error: {err}")
        return False
        
    logger.info(f"🛑 Position {ticket} closed successfully due to SL/TP verification failure.")
    return True


def verify_sl_tp_consistency(ticket: int, expected_sl: float, expected_tp: float) -> bool:
    """
    Verifies that the open position's SL and TP match the requested ones.
    If they differ (e.g., broker adjustment), closes the trade immediately.
    
    Args:
        ticket: The position ticket ID.
        expected_sl: The SL price we requested.
        expected_tp: The TP price we requested.
        
    Returns:
        True if consistent, False if a mismatch was found and trade was closed.
    """
    if not initialize_mt5():
        return True # Assume OK if we can't check, to avoid accidental closures

    # Give the broker a tiny bit of time to register the position fully if needed
    time.sleep(0.1) 
    
    with mt5_lock:
        positions = mt5.positions_get(ticket=ticket)
    if not positions:
        logger.warning(f"⚠️ Verification: Position {ticket} not found (might have been closed already).")
        return True
    
    pos = positions[0]
    actual_sl = pos.sl
    actual_tp = pos.tp
    symbol = pos.symbol
    
    # === WHY DO WE NEED THE THRESHOLD? ===
    # 1. Floating Point Math: Computers store numbers like 1.05001 with tiny 
    #    inaccuracies (e.g., 1.050010000002). A direct '==' comparison would fail.
    # 2. Broker Rounding: Brokers might round your 5th decimal slightly differently
    #    than your calculation. 
    # By using 'threshold' (1.5 times the smallest pip/point), we ensure that 
    # if the difference is negligible, we don't close the trade.
    
    with mt5_lock:
        sym_info = mt5.symbol_info(symbol)
    threshold = (sym_info.point * 1.5) if sym_info else 0.00001
    
    sl_match = abs(actual_sl - expected_sl) < threshold if expected_sl > 0 else (actual_sl == 0)
    tp_match = abs(actual_tp - expected_tp) < threshold if expected_tp > 0 else (actual_tp == 0)
    
    if not sl_match or not tp_match:
        logger.warning(
            f"❌ SL/TP MISMATCH for ticket {ticket} ({symbol})!"
            f"\n   Requested: SL {expected_sl:.5f}, TP {expected_tp:.5f}"
            f"\n   Actual:    SL {actual_sl:.5f}, TP {actual_tp:.5f}"
        )
        close_position(ticket)
        return False
        
    logger.info(f"✅ SL/TP verified for ticket {ticket} ({symbol}).")
    return True


def is_trade_open(symbol: str) -> tuple[bool, str]:
    """
    Checks if a new trade can be opened for the given symbol.
    
    Constraints:
    1. Global limit: Max 4 active trades across all symbols (filtered by Magic Number).
    2. Time limit: At least 3 hours difference between trades for the same symbol.
    
    Returns:
        tuple (is_blocked, reason)
    """
    if not initialize_mt5():
        return True, "MT5 initialization failed"
        
    # 1. Total active trades limit check
    with mt5_lock:
        all_positions = mt5.positions_get()
    if all_positions is None:
        return False, "" # No positions at all
        
    bot_positions = [p for p in all_positions if p.magic == MT5_MAGIC_NUMBER]
    if len(bot_positions) >= MT5_MAX_ACTIVE_TRADES:
        return True, f"Global limit reached: {len(bot_positions)} active trades"

    # 2. Per-symbol time limit check
    current_time = time.time()
    
    # 2a. Check active positions
    symbol_positions = [p for p in bot_positions if p.symbol == symbol]
    if symbol_positions:
        most_recent_time = max(p.time for p in symbol_positions)
        hours_since_last_pos = (current_time - most_recent_time) / 3600
        if hours_since_last_pos < MT5_MIN_TRADE_INTERVAL_HOURS:
            return True, f"Recent active position for {symbol} found ({hours_since_last_pos:.1f}h ago)."

    # 2b. Check historical deals (last 24 hours to be safe)
    # This prevents re-opening if a trade was closed (e.g., by safety logic)
    from_date = datetime.now() - timedelta(days=1)
    with mt5_lock:
        history = mt5.history_deals_get(from_date, datetime.now(), group=f"*{symbol}*")
        
    if history:
        # Filter by magic number and entry type (DEAL_ENTRY_IN means trade opening)
        bot_deals = [d for d in history if d.magic == MT5_MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_IN]
        if bot_deals:
            last_deal_time = max(d.time for d in bot_deals)
            hours_since_last_deal = (current_time - last_deal_time) / 3600
            if hours_since_last_deal < MT5_MIN_TRADE_INTERVAL_HOURS:
                return True, f"Recent historical trade for {symbol} found ({hours_since_last_deal:.1f}h ago)."
            
    return False, ""
