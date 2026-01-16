import time
from logger import get_logger
from configuration.broker_config import MT5_MAGIC_NUMBER, MT5_DEVIATION, MT5_EXPIRATION_MINUTES

logger = get_logger(__name__)

class MT5Trader:
    """Handles trading operations like placing orders and closing positions."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def place_order(self, symbol: str, order_type: int, volume: float, price: float = 0.0, 
                    sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, 
                    magic: int = MT5_MAGIC_NUMBER, comment: str = "", 
                    expiration_minutes: int = MT5_EXPIRATION_MINUTES):
        """Place an order in MT5 with automatic expiration."""
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
                price = tick.ask if order_type == self.mt5.ORDER_TYPE_BUY else tick.bid

            # 3. Normalize prices (Round to symbol's digits)
            price = round(price, symbol_info.digits)
            sl = round(sl, symbol_info.digits) if sl > 0 else 0.0
            tp = round(tp, symbol_info.digits) if tp > 0 else 0.0

            # 4. Calculate expiration timestamp (Server time + minutes)
            expiration_time = int(tick.time + (expiration_minutes * 60))

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
        """Closes an active position by its ticket ID."""
        if not self.connection.initialize():
            return False

        with self.connection.lock:
            positions = self.mt5.positions_get(ticket=ticket)
            if not positions:
                logger.error(f"❌ Failed to close position {ticket}: Position not found.")
                return False
            
            position = positions[0]
            symbol = position.symbol
            volume = position.volume
            
            tick = self.mt5.symbol_info_tick(symbol)
            if position.type == self.mt5.POSITION_TYPE_BUY:
                order_type = self.mt5.ORDER_TYPE_SELL
                price = tick.bid if tick else None
            else:
                order_type = self.mt5.ORDER_TYPE_BUY
                price = tick.ask if tick else None

            if not price:
                logger.error(f"❌ Failed to close position {ticket}: Failed to get current price for {symbol}.")
                return False
            
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": MT5_DEVIATION,
                "magic": MT5_MAGIC_NUMBER,
                "comment": "Auto-close: SL/TP mismatch",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }
            
            result = self.mt5.order_send(request)

        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            err = self.mt5.last_error() if self.mt5 else "Unknown"
            logger.error(f"❌ Failed to close position {ticket}. Result: {result.retcode if result else 'None'}, Error: {err}")
            return False
            
        logger.info(f"🛑 Position {ticket} closed successfully due to SL/TP verification failure.")
        return True

    def verify_sl_tp_consistency(self, ticket: int, expected_sl: float, expected_tp: float) -> bool:
        """Verifies that the open position's SL and TP match the requested ones."""
        if not self.connection.initialize():
            return True

        time.sleep(0.1) 
        
        with self.connection.lock:
            positions = self.mt5.positions_get(ticket=ticket)
            if not positions:
                logger.warning(f"⚠️ Verification: Position {ticket} not found (might have been closed already).")
                return True
            
            pos = positions[0]
            actual_sl = pos.sl
            actual_tp = pos.tp
            symbol = pos.symbol
            
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
