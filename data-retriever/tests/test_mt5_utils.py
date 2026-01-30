"""
Shared utilities for MT5 test suite.

This module provides common setup functions, mock configurations, and helper utilities
used across all MT5 test modules to ensure consistency and reduce code duplication.
"""

import sys
import os
from unittest.mock import MagicMock
import MetaTrader5 as mt5

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from externals.meta_trader.connection import MT5Connection
from logger import get_logger

logger = get_logger(__name__)

# Test configuration constants
SYMBOL = "EURUSD"
LOT_SIZE = 0.01
PIP_VALUE = 0.0001


def setup_mock_mt5(mock_mt5):
    """
    Inject standard MT5 constants into a mock object.
    
    This function sets up all necessary MT5 constants that are used throughout
    the test suite, ensuring consistent behavior across all test modules.
    
    Args:
        mock_mt5: A MagicMock object that will receive MT5 constants as attributes.
    """
    constants = [
        'TRADE_ACTION_DEAL', 'ORDER_TIME_SPECIFIED', 'ORDER_TYPE_SELL', 'ORDER_TYPE_BUY',
        'POSITION_TYPE_BUY', 'POSITION_TYPE_SELL', 'ORDER_TIME_GTC', 'ORDER_FILLING_IOC',
        'TRADE_RETCODE_DONE', 'TRADE_RETCODE_REJECT', 'TRADE_RETCODE_CANCEL',
        'SYMBOL_TRADE_MODE_DISABLED', 'SYMBOL_TRADE_MODE_CLOSEONLY', 'SYMBOL_TRADE_MODE_FULL',
        'TRADE_RETCODE_FROZEN', 'TRADE_RETCODE_MARKET_CLOSED', 'TRADE_RETCODE_NO_MONEY',
        'TRADE_RETCODE_PRICE_OFF', 'TRADE_RETCODE_PRICE_OVER', 'TRADE_RETCODE_INVALID_FILL',
        'TRADE_RETCODE_REQUOTE', 'TRADE_RETCODE_OFF_QUOTES', 'TRADE_RETCODE_BUSY',
        'TRADE_RETCODE_INVALID_VOLUME', 'TRADE_RETCODE_INVALID_STOPS', 'TRADE_RETCODE_TOO_MANY_REQUESTS'
    ]
    # Map of constants to their actual MT5 values or fallback values
    constant_values = {
        'TRADE_RETCODE_MARKET_CLOSED': 10018,
        'TRADE_RETCODE_NO_MONEY': 10019,
        'TRADE_RETCODE_AUTOTRADING_DISABLED': 10026,
    }
    for const in constants:
        value = getattr(mt5, const, None)
        if value is None:
            value = constant_values.get(const, 0)
        setattr(mock_mt5, const, value)
    
    # Standard MT5 methods that should return something other than a MagicMock
    mock_mt5.last_error.return_value = (1, "Success")


def create_mock_connection(initialize_success=True, symbol_info=None, tick_info=None):
    """
    Create a mock MT5Connection with standard configuration.
    
    Args:
        initialize_success: Whether connection initialization should succeed.
        symbol_info: Optional custom symbol info mock. If None, creates default.
        tick_info: Optional custom tick info mock. If None, creates default.
    
    Returns:
        A configured MagicMock object that mimics MT5Connection behavior.
    """
    mock_conn = MagicMock(spec=MT5Connection)
    mock_conn.initialize.return_value = initialize_success
    mock_conn.mt5 = MagicMock()
    setup_mock_mt5(mock_conn.mt5)
    mock_conn.lock = MagicMock()
    
    # Setup default symbol info if not provided
    if symbol_info is None:
        sym_info = create_symbol_info()
        mock_conn.mt5.symbol_info.return_value = sym_info
    else:
        mock_conn.mt5.symbol_info.return_value = symbol_info
    
    # Setup default tick info if not provided
    if tick_info is None:
        mock_conn.mt5.symbol_info_tick.return_value = MagicMock(time=1000)
    else:
        mock_conn.mt5.symbol_info_tick.return_value = tick_info
    
    return mock_conn


def create_symbol_info(digits=5, stops_level=0, freeze_level=0, 
                      trade_mode=None, visible=True, point=None,
                      volume_step=0.01, volume_min=0.01, volume_max=100.0):
    """
    Create a mock symbol info object with specified parameters.
    
    Args:
        digits: Number of decimal places for the symbol.
        stops_level: Minimum stops level in points.
        freeze_level: Freeze level in points.
        trade_mode: Trade mode constant (defaults to SYMBOL_TRADE_MODE_FULL).
        visible: Whether symbol is visible in market watch.
        point: Point value (defaults to 10^(-digits)).
        volume_step: Minimum volume increment.
        volume_min: Minimum allowed volume.
        volume_max: Maximum allowed volume.
    
    Returns:
        A configured MagicMock object representing symbol information.
    """
    sym_info = MagicMock()
    sym_info.visible = visible
    sym_info.digits = digits
    sym_info.trade_stops_level = stops_level
    sym_info.trade_freeze_level = freeze_level
    sym_info.trade_mode = trade_mode or mt5.SYMBOL_TRADE_MODE_FULL
    sym_info.point = point if point is not None else (10 ** (-digits))
    sym_info.volume_step = volume_step
    sym_info.volume_min = volume_min
    sym_info.volume_max = volume_max
    return sym_info


def log_test(name: str, passed: bool, details: str = ""):
    """
    Log test result with consistent formatting.
    
    Args:
        name: Test name or description.
        passed: Whether the test passed.
        details: Optional additional details to log (typically for failures).
    """
    status = "[PASS]" if passed else "[FAIL]"
    if passed:
        logger.info(f"  {status}: {name}")
    else:
        logger.error(f"  {status}: {name}")
        if details:
            logger.error(f"         {details}")
