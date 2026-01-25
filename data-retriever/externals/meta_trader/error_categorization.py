"""MT5 error code categorization for appropriate handling and logging.

Categorizes MT5 trade return codes into:
- FATAL: Abort immediately, log as error, don't retry
- TRANSIENT: Log as warning, consider retry mechanism
- MARKET_MOVED: Log as info, normal market behavior
- MARKET_CLOSED: Log as info, market is closed (not a system problem)
- PARTIAL_SUCCESS: Log as info, partial execution (success but not full volume)
"""
from enum import Enum
from typing import Dict, Set

class ErrorCategory(Enum):
    """Error categories for MT5 trade return codes."""
    FATAL = "fatal"          # Abort, log as error, don't retry
    TRANSIENT = "transient"  # Log as warning, consider retry
    MARKET_MOVED = "market_moved"  # Log as info, normal market behavior
    MARKET_CLOSED = "market_closed"  # Log as info, market is closed (not a system problem)
    PARTIAL_SUCCESS = "partial_success"  # Log as info, partial execution (success but not full volume)


class MT5ErrorCategorizer:
    """Categorizes MT5 error codes for appropriate handling."""
    
    # FATAL errors - abort immediately, log as error, don't retry
    # These indicate fundamental problems: invalid parameters, insufficient funds, trading disabled, configuration issues
    FATAL_ERRORS: Set[int] = {
        10006,  # Request rejected - server rejected our request (likely invalid parameters)
        10013,  # Invalid request - our request structure is wrong
        10014,  # Invalid volume - our volume calculation is wrong
        10015,  # Invalid price - our price is wrong
        10016,  # Invalid stops (SL/TP) - our SL/TP calculation is wrong
        10017,  # Trade disabled - trading is disabled for this symbol
        10019,  # Insufficient funds - no money, won't work until funded
        10022,  # Invalid order expiration - our expiration is wrong
        10026,  # AutoTrading disabled by server - configuration issue, not a connection problem
        10027,  # AutoTrading disabled in terminal - user needs to enable algo trading
        10030,  # Invalid SL/TP for this symbol - our SL/TP doesn't meet symbol requirements
        10048,  # Invalid order comment
        10049,  # Invalid order magic number
        10050,  # Invalid order symbol
        10052,  # Invalid order volume
        10053,  # Invalid order type
        10054,  # Invalid order filling mode
        10055,  # Invalid order expiration type
        10056,  # Invalid order expiration date
        10057,  # Invalid order stop level
        10058,  # Invalid order price
        10059,  # Invalid order stop loss
        10060,  # Invalid order take profit
    }
    
    # TRANSIENT errors - log as warning, consider retry mechanism
    # These indicate temporary server/context issues that might resolve on retry
    TRANSIENT_ERRORS: Set[int] = {
        10009,  # Context busy - server is busy, try again later
        10011,  # Position is frozen - position temporarily frozen, try again later
        10024,  # Too frequent requests - rate limited, wait and retry
    }
    
    # MARKET_MOVED errors - log as info, normal market behavior
    # These indicate price/quote changes - retry with updated prices
    MARKET_MOVED_ERRORS: Set[int] = {
        10004,  # Requote - price changed, retry with new price
        10020,  # Prices changed - price changed during execution, retry with new price
        10021,  # No quotes - broker can't provide quotes (temporary), retry when quotes available
        10025,  # Requote - same as 10004, price changed, retry with new price
    }
    
    # MARKET_CLOSED errors - log as info, market is closed (not a system problem)
    # This is normal market behavior, not an error in our system
    MARKET_CLOSED_ERRORS: Set[int] = {
        10018,  # Market closed - market is closed, will work when market opens
    }
    
    # PARTIAL_SUCCESS - log as info, partial execution (success but not full volume)
    # This is actually a success code, not an error - trade was partially executed
    PARTIAL_SUCCESS_CODES: Set[int] = {
        10010,  # Only part of request completed - partial execution (success, but not full volume)
    }
    
    # Error descriptions
    ERROR_DESCRIPTIONS: Dict[int, str] = {
        10004: "Requote - price changed",
        10006: "Request rejected",
        10007: "Request canceled by trader",
        10009: "Context busy",
        10010: "Only part of request completed",
        10011: "Position is frozen",
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
        10025: "Requote",
        10026: "AutoTrading disabled by server",
        10027: "AutoTrading disabled in terminal (enable Algo Trading button)",
        10030: "Invalid SL/TP for this symbol",
        10048: "Invalid order comment",
        10049: "Invalid order magic number",
        10050: "Invalid order symbol",
        10052: "Invalid order volume",
        10053: "Invalid order type",
        10054: "Invalid order filling mode",
        10055: "Invalid order expiration type",
        10056: "Invalid order expiration date",
        10057: "Invalid order stop level",
        10058: "Invalid order price",
        10059: "Invalid order stop loss",
        10060: "Invalid order take profit",
    }
    
    @classmethod
    def categorize(cls, retcode: int) -> ErrorCategory:
        """Categorize an MT5 error code.
        
        Args:
            retcode: MT5 trade return code
            
        Returns:
            ErrorCategory enum value
        """
        if retcode in cls.FATAL_ERRORS:
            return ErrorCategory.FATAL
        elif retcode in cls.TRANSIENT_ERRORS:
            return ErrorCategory.TRANSIENT
        elif retcode in cls.MARKET_MOVED_ERRORS:
            return ErrorCategory.MARKET_MOVED
        elif retcode in cls.MARKET_CLOSED_ERRORS:
            return ErrorCategory.MARKET_CLOSED
        elif retcode in cls.PARTIAL_SUCCESS_CODES:
            return ErrorCategory.PARTIAL_SUCCESS
        else:
            # Unknown errors default to FATAL for safety
            return ErrorCategory.FATAL
    
    @classmethod
    def get_description(cls, retcode: int) -> str:
        """Get human-readable description for an error code.
        
        Args:
            retcode: MT5 trade return code
            
        Returns:
            Error description or "Unknown error"
        """
        return cls.ERROR_DESCRIPTIONS.get(retcode, "Unknown error")
    
    @classmethod
    def is_retryable(cls, retcode: int) -> bool:
        """Check if an error code is potentially retryable.
        
        Args:
            retcode: MT5 trade return code
            
        Returns:
            True if error might be retryable, False otherwise
        """
        category = cls.categorize(retcode)
        return category == ErrorCategory.TRANSIENT or category == ErrorCategory.MARKET_MOVED
    
    @classmethod
    def should_abort(cls, retcode: int) -> bool:
        """Check if an error should cause immediate abort.
        
        Args:
            retcode: MT5 trade return code
            
        Returns:
            True if error is fatal and should abort, False otherwise
        """
        return cls.categorize(retcode) == ErrorCategory.FATAL
