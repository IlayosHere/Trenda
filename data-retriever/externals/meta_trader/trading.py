import time
from typing import NamedTuple, Optional, Any, Tuple
from logger import get_logger
from configuration.broker_config import (
    MT5_MAGIC_NUMBER, MT5_EMERGENCY_MAGIC_NUMBER, MT5_DEVIATION, 
    MT5_EXPIRATION_SECONDS, MT5_CLOSE_RETRY_ATTEMPTS,
    MT5_SL_TP_THRESHOLD_MULTIPLIER, MT5_PRICE_THRESHOLD_FALLBACK,
    MT5_VERIFICATION_SLEEP
)
from configuration.trading_config import MT5_ORDER_COMMENT
from .safeguards import _safeguards

logger = get_logger(__name__)

class CloseAttemptStatus(NamedTuple):
    """Result of a single position closure attempt."""
    success: bool
    should_retry: bool

class MT5Trader:
    """Handles trading operations like placing orders and closing positions."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def place_order(self, symbol: str, order_type: int, volume: float, price: float = 0.0, 
                    sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, 
                    magic: int = MT5_MAGIC_NUMBER, comment: str = MT5_ORDER_COMMENT,
                    expiration_seconds: int = MT5_EXPIRATION_SECONDS) -> Optional[Any]:
        """Place an order in MT5 with a strict expiration window.
        
        Returns:
            mt5.OrderSendResult or None: The result of the order placement.
        """
        if not self.connection.initialize():
            return None

        with self.connection.lock:
            symbol_info = self._ensure_symbol_available(symbol)
            if symbol_info is None:
                return None

            if not self._validate_trade_mode(symbol, symbol_info):
                return None

            if not self._validate_price(symbol, price):
                return None

            price, sl, tp = self._normalize_prices(symbol, symbol_info, price, sl, tp)
            if price is None:
                return None

            if not self._validate_sl_tp_distances(symbol, symbol_info, price, sl, tp):
                return None

            expiration_time = self._calculate_expiration_time(symbol, expiration_seconds)
            if expiration_time is None:
                return None

            request = self._build_order_request(
                symbol, order_type, volume, price, sl, tp, 
                deviation, magic, comment, expiration_time
            )

            result = self.mt5.order_send(request)
        
        return self._process_order_result(symbol, order_type, volume, price, result)

    def _ensure_symbol_available(self, symbol: str) -> Optional[Any]:
        """Ensure symbol is visible and select it if needed.
        
        Returns:
            Symbol info if available, None otherwise.
        """
        symbol_info = self.mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.error(f"Symbol {symbol} not found.")
            return None
        
        if not symbol_info.visible:
            if not self.mt5.symbol_select(symbol, True):
                logger.error(f"Failed to select symbol {symbol}.")
                return None
        
        return symbol_info

    def _validate_trade_mode(self, symbol: str, symbol_info: Any) -> bool:
        """Validate that trading is allowed for the symbol.
        
        Returns:
            True if trading is allowed, False otherwise.
        """
        if symbol_info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_DISABLED:
            logger.error(f"Order failed: Trading is DISABLED for {symbol}.")
            return False
        if symbol_info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_CLOSEONLY:
            logger.error(f"Order failed: Symbol {symbol} is in CLOSE-ONLY mode.")
            return False
        return True

    def _validate_price(self, symbol: str, price: float) -> bool:
        """Validate that price is not zero.
        
        Returns:
            True if price is valid, False otherwise.
        """
        if price == 0.0:
            logger.error(f"Order failed for {symbol}: price is 0.0. A valid price must be provided.")
            return False
        return True

    def _normalize_prices(self, symbol: str, symbol_info: Any, price: float, 
                         sl: float, tp: float) -> Tuple[Optional[float], float, float]:
        """Normalize prices by rounding to symbol's digits and validate SL/TP are non-negative.
        
        Returns:
            Tuple of (normalized_price, normalized_sl, normalized_tp) or (None, 0.0, 0.0) if invalid.
        """
        price = round(price, symbol_info.digits)
        
        if sl < 0 or tp < 0:
            logger.error(f"Order failed for {symbol}: SL/TP cannot be negative (sl={sl}, tp={tp}).")
            return None, 0.0, 0.0

        sl = round(sl, symbol_info.digits) if sl > 0 else 0.0
        tp = round(tp, symbol_info.digits) if tp > 0 else 0.0
        
        return price, sl, tp

    def _validate_sl_tp_distances(self, symbol: str, symbol_info: Any, 
                                  price: float, sl: float, tp: float) -> bool:
        """Validate that SL/TP distances meet minimum requirements (Stops Level & Freeze Level).
        
        Returns:
            True if distances are valid, False otherwise.
        """
        if sl == 0 and tp == 0:
            return True

        min_dist_points = max(symbol_info.trade_stops_level, symbol_info.trade_freeze_level)
        min_dist_price = min_dist_points * symbol_info.point
        
        if sl > 0:
            dist_sl = abs(price - sl)
            if dist_sl < min_dist_price:
                logger.error(f"Order failed for {symbol}: SL too close to price. "
                             f"Dist: {dist_sl:.5f}, Min: {min_dist_price:.5f} ({min_dist_points} pts)")
                return False
        
        if tp > 0:
            dist_tp = abs(tp - price)
            if dist_tp < min_dist_price:
                logger.error(f"Order failed for {symbol}: TP too close to price. "
                             f"Dist: {dist_tp:.5f}, Min: {min_dist_price:.5f} ({min_dist_points} pts)")
                return False
        
        return True

    def _calculate_expiration_time(self, symbol: str, expiration_seconds: int) -> Optional[int]:
        """Calculate expiration timestamp based on current tick time.
        
        Returns:
            Expiration timestamp or None if tick info cannot be retrieved.
        """
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"Failed to get tick info for {symbol}. Error: {self.mt5.last_error()}")
            return None
        return int(tick.time + expiration_seconds)

    def _build_order_request(self, symbol: str, order_type: int, volume: float, 
                            price: float, sl: float, tp: float, deviation: int,
                            magic: int, comment: str, expiration_time: int) -> dict:
        """Build the order request dictionary.
        
        Returns:
            Dictionary containing order request parameters.
        """
        return {
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

    def _process_order_result(self, symbol: str, order_type: int, volume: float, 
                              price: float, result: Optional[Any]) -> Optional[Any]:
        """Process the order send result and log appropriately.
        
        Returns:
            Order result if successful, None or result object if failed.
        """
        if result is None:
            logger.error(f"Order send failed for {symbol}. Result is None.")
            return None

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            self._log_order_error(symbol, result)
            return result

        logger.info(f"Success: Order placed - sym:{symbol}, vol:{volume}, type:{order_type}, price:{price}, ticket:{result.order}")
        return result

    def _log_order_error(self, symbol: str, result: Any):
        """Helper to log detailed MT5 order errors."""
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
        desc = error_messages.get(result.retcode, "Unknown error")
        logger.error(f"Order failed for {symbol}. Retcode: {result.retcode} ({desc}), MT5 Error: {self.mt5.last_error()}")

    def close_position(self, ticket: int) -> bool:
        """Closes an active position by its ticket ID with retry logic and verification."""
        if not self.connection.initialize():
            return False

        for attempt in range(1, MT5_CLOSE_RETRY_ATTEMPTS + 1):
            status = self._attempt_close(ticket, attempt)
            if status.success:
                break
            if not status.should_retry:
                return False
            
            logger.info(f"Retrying close for ticket {ticket} in 1s...")
            time.sleep(1)
        else:
            # All retry attempts exhausted - this is a critical failure
            _safeguards.trigger_emergency_lock(
                f"Failed to close position {ticket} after {MT5_CLOSE_RETRY_ATTEMPTS} attempts"
            )
            logger.critical(f"EMERGENCY: Failed to close position {ticket} after all attempts.")
            return False

        return self._verify_closure(ticket)

    def _attempt_close(self, ticket: int, attempt: int) -> CloseAttemptStatus:
        """Performs a single closing attempt."""
        with self.connection.lock:
            pos = self._get_active_position(ticket)
            if not pos:
                if attempt == 1:
                    logger.warning(f"Close position {ticket}: Not found (already closed).")
                return CloseAttemptStatus(True, False)
            
            tick = self.mt5.symbol_info_tick(pos.symbol)
            if not tick:
                logger.error(f"Close attempt {attempt}: Failed to get tick for {pos.symbol}.")
                return CloseAttemptStatus(False, True)

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

        if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:
            return CloseAttemptStatus(True, False)
            
        err_msg = f"Retcode: {result.retcode if result else 'None'}, Error: {self.mt5.last_error()}"
        if result and result.retcode == self.mt5.TRADE_RETCODE_FROZEN:
            logger.warning(f"Close attempt {attempt} for ticket {ticket}: Position is FROZEN. Retrying...")
        else:
            logger.error(f"Close attempt {attempt} failed for ticket {ticket}. {err_msg}")
        
        return CloseAttemptStatus(False, True)

    def _verify_closure(self, ticket: int) -> bool:
        """Final check to ensure the position is actually closed on the server."""
        time.sleep(0.5) 
        with self.connection.lock:
            if self._get_active_position(ticket):
                # Position still open after close signal - critical failure
                _safeguards.trigger_emergency_lock(
                    f"Position {ticket} still OPEN after close signal was confirmed"
                )
                logger.critical(f"VERIFICATION FAILED: Ticket {ticket} still OPEN after close signal!")
                return False

        logger.info(f"Position {ticket} closed and verified successfully.")
        return True

    def _get_active_position(self, ticket: int) -> Optional[Any]:
        """Helper to get a single active position by its unique ticket ID."""
        positions = self.mt5.positions_get(ticket=ticket)
        return positions[0] if positions else None

    def verify_position_consistency(
        self, 
        ticket: int, 
        expected_sl: float, 
        expected_tp: float,
        expected_volume: float = 0.0,
        expected_price: float = 0.0
    ) -> bool:
        """Verifies that an open position's parameters match the requested values.
        
        This prevents hidden broker modifications (e.g., sliding SL/TP or filling 
        different volumes/prices) from going unnoticed.
        """
        if not self.connection.initialize():
            logger.error("Cannot verify position: MT5 initialization failed")
            return False  # Safer default: treat as unverified

        time.sleep(MT5_VERIFICATION_SLEEP) 
        
        with self.connection.lock:
            pos = self._get_active_position(ticket)
            if not pos:
                logger.warning(f"Verification: Position {ticket} not found (closed?).")
                return True

            sym_info = self.mt5.symbol_info(pos.symbol)
            point = sym_info.point if sym_info else 0.00001
            threshold = (point * MT5_SL_TP_THRESHOLD_MULTIPLIER) if sym_info else MT5_PRICE_THRESHOLD_FALLBACK
            
            # Capture all values atomically inside lock
            symbol_name = pos.symbol
            actual_sl, actual_tp = pos.sl, pos.tp
            actual_volume, actual_price = pos.volume, pos.price_open
        
            # 1. SL/TP Consistency
            sl_match = abs(actual_sl - expected_sl) < threshold if expected_sl > 0 else (actual_sl == 0)
            tp_match = abs(actual_tp - expected_tp) < threshold if expected_tp > 0 else (actual_tp == 0)
            
            if not sl_match or not tp_match:
                logger.warning(f"SL/TP MISMATCH for ticket {ticket} ({symbol_name})! "
                               f"Requested: {expected_sl}/{expected_tp}, Actual: {actual_sl}/{actual_tp}")
                # Note: close_position will acquire its own lock, so we exit this block first
                needs_close = "sl_tp"
            elif expected_volume > 0 and abs(actual_volume - expected_volume) > 0.00001:
                # 2. Volume Consistency (Exact match with small epsilon)
                logger.warning(f"VOLUME MISMATCH for ticket {ticket} ({symbol_name})! "
                               f"Requested: {expected_volume}, Actual: {actual_volume}")
                needs_close = "volume"
            elif expected_price > 0:
                # 3. Open Price Consistency (Slippage check)
                max_allowed_slip = point * MT5_DEVIATION
                actual_slippage = abs(actual_price - expected_price)
                if actual_slippage > max_allowed_slip:
                    logger.warning(
                        f"PRICE MISMATCH (SLIPPAGE) for ticket {ticket} ({symbol_name})! "
                        f"Requested: {expected_price}, Actual: {actual_price}, "
                        f"Slippage: {actual_slippage:.5f}, Limit: {max_allowed_slip:.5f}"
                    )
                    needs_close = "price"
                else:
                    needs_close = None
            else:
                needs_close = None
        
        # Close position outside the lock if needed
        if needs_close:
            self.close_position(ticket)
            return False

        logger.info(f"Position parameters verified for ticket {ticket} ({symbol_name}).")
        return True
