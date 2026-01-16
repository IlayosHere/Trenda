import time
from configuration.broker_config import (
    MT5_MAGIC_NUMBER, MT5_EMERGENCY_MAGIC_NUMBER, MT5_DEVIATION, 
    MT5_EXPIRATION_SECONDS, MT5_CLOSE_RETRY_ATTEMPTS
)

logger = get_logger(__name__)

class MT5Trader:
    """Handles trading operations like placing orders and closing positions."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def place_order(self, symbol: str, order_type: int, volume: float, price: float = 0.0, 
                    sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, 
                    magic: int = MT5_MAGIC_NUMBER, comment: str = "",
                    expiration_seconds: int = MT5_EXPIRATION_SECONDS):
        """Place an order in MT5 with a strict expiration window."""
        if not self.connection.initialize():
            return None

        with self.connection.lock:
            # 1. Ensure symbol is visible and select it
            symbol_info = self.mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.error(f"Symbol {symbol} not found.")
                return None
            
            if not symbol_info.visible:
                if not self.mt5.symbol_select(symbol, True):
                    logger.error(f"Failed to select symbol {symbol}.")
                    return None

            # 2. Get current price
            tick = self.mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error(f"Failed to get tick info for {symbol}. Error: {self.mt5.last_error()}")
                return None

            if price == 0.0:
                logger.error(f"Order failed for {symbol}: price is 0.0. A valid price must be provided.")
                return None

            # 3. Normalize prices (Round to symbol's digits)
            price = round(price, symbol_info.digits)
            sl = round(sl, symbol_info.digits) if sl > 0 else 0.0
            tp = round(tp, symbol_info.digits) if tp > 0 else 0.0

            # 4. Calculate expiration timestamp (Server time + configured seconds)
            # We use a short window because data is already ~60-80s old.
            # If the broker cannot fill the order within this window, it should be killed.
            expiration_time = int(tick.time + expiration_seconds)

            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": deviation,
                "magic": magic,
                "comment": comment,
                # We use SPECIFIED with a short expiration to "kill" the order if not filled 
                # within our 90s window (relevant if the order sits in a queue).
                "type_time": self.mt5.ORDER_TIME_SPECIFIED,
                "expiration": expiration_time,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }

            result = self.mt5.order_send(request)
        
        if result is None:
            logger.error(f"Order send failed for {symbol}. Result is None.")
            return None

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            # Common MT5 error codes for better debugging
            error_messages = {
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
                10026: "AutoTrading disabled by server",
                10027: "AutoTrading disabled in terminal (enable Algo Trading button)",
                10030: "Invalid SL/TP for this symbol",
            }
            error_desc = error_messages.get(result.retcode, "Unknown error")
            logger.error(f"Order failed for {symbol}. Retcode: {result.retcode} ({error_desc}), MT5 Error: {self.mt5.last_error()}")
            return result

        # 5. Success Logging
        logger.info(f"✅ Success: Order placed - sym:{symbol}, vol:{volume}, type:{order_type}, price:{price}, ticket:{result.order}")
        
        return result

    def close_position(self, ticket: int) -> bool:
        """Closes an active position by its ticket ID with retry logic and verification."""
        if not self.connection.initialize():
            return False

        # 1. Try to close (configurable attempts)
        for attempt in range(1, MT5_CLOSE_RETRY_ATTEMPTS + 1):
            success, should_retry = self._attempt_close(ticket, attempt)
            if success:
                break
            if not should_retry:
                return False
            
            logger.info(f"🔄 Retrying close for ticket {ticket} in 1s...")
            time.sleep(1)
        else:
            logger.critical(f"🚨 EMERGENCY: Failed to close position {ticket} after all attempts.")
            return False

        # 2. Final server-side verification
        return self._verify_closure(ticket)

    def _attempt_close(self, ticket: int, attempt: int) -> tuple[bool, bool]:
        """Performs a single closing attempt. Returns (success, should_retry)."""
        with self.connection.lock:
            # Check if position exists
            pos = self._get_active_position(ticket)
            if not pos:
                if attempt == 1:
                    logger.warning(f"⚠️ Close position {ticket}: Not found (already closed).")
                    return True, False
                return True, False # Success on retry if it's gone
            
            # Prepare request
            tick = self.mt5.symbol_info_tick(pos.symbol)
            if not tick:
                logger.error(f"❌ Close attempt {attempt}: Failed to get tick for {pos.symbol}.")
                return False, True

            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": self.mt5.ORDER_TYPE_SELL if pos.type == self.mt5.POSITION_TYPE_BUY else self.mt5.ORDER_TYPE_BUY,
                "position": ticket,
                "price": tick.bid if pos.type == self.mt5.POSITION_TYPE_BUY else tick.ask,
                "deviation": MT5_DEVIATION,
                "magic": MT5_EMERGENCY_MAGIC_NUMBER,
                "comment": "Auto-close",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }
            
            result = self.mt5.order_send(request)

        # Evaluate result
        if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:
            return True, False
            
        err_msg = f"Retcode: {result.retcode if result else 'None'}, Error: {self.mt5.last_error()}"
        logger.error(f"❌ Close attempt {attempt} failed for ticket {ticket}. {err_msg}")
        return False, True

    def _verify_closure(self, ticket: int) -> bool:
        """Final check to ensure the position is actually closed on the server."""
        time.sleep(0.5) # Wait for server synchronization
        with self.connection.lock:
            if self._get_active_position(ticket):
                logger.critical(f"🚨 VERIFICATION FAILED: Ticket {ticket} still OPEN after successful close signal!")
                # TODO: Trigger extreme priority alert (WhatsApp)
                return False

        logger.info(f"🛑 Position {ticket} closed and verified successfully.")
        return True

    def _get_active_position(self, ticket: int):
        """Helper to get a single active position by its unique ticket ID.
        MT5 returns a tuple even for unique tickets, so we take the first item.
        """
        positions = self.mt5.positions_get(ticket=ticket)
        return positions[0] if positions else None

    def verify_sl_tp_consistency(self, ticket: int, expected_sl: float, expected_tp: float) -> bool:
        """Verifies that the open position's SL and TP match the requested ones."""
        if not self.connection.initialize():
            return True

        time.sleep(0.1) 
        
        with self.connection.lock:
            pos = self._get_active_position(ticket)
            if not pos:
                logger.warning(f"⚠️ Verification: Position {ticket} not found (might have been closed already).")
                return True
            
            actual_sl = pos.sl
            actual_tp = pos.tp
            symbol = pos.symbol
            
            # 1.5 point threshold handles tiny broker-side floating point rounding errors
            sym_info = self.mt5.symbol_info(symbol)
            threshold = (sym_info.point * 1.5) if sym_info else 0.00001
        
        sl_match = abs(actual_sl - expected_sl) < threshold if expected_sl > 0 else (actual_sl == 0)
        tp_match = abs(actual_tp - expected_tp) < threshold if expected_tp > 0 else (actual_tp == 0)
        
        if not sl_match or not tp_match:
            logger.warning(
                f"❌ SL/TP MISMATCH for ticket {ticket} ({symbol})!"
                f"\n   Requested: SL {expected_sl:.5f}, TP {expected_tp:.5f}"
                f"\n   Actual:    SL {actual_sl:.5f}, TP {actual_tp:.5f}"
            )
            self.close_position(ticket)
            return False
            
        logger.info(f"✅ SL/TP verified for ticket {ticket} ({symbol}).")
        return True
