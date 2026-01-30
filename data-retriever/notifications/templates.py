"""
Template definitions for notification messages.

Each event type maps to a MessageTemplate that defines how to render
the notification message from a payload dictionary.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import (
    CHANNEL_TRADE_EXECUTIONS,
    CHANNEL_TRADE_FAILURES,
    CHANNEL_TRADE_OPPORTUNITIES,
    CHANNEL_SYSTEM_STATUS,
    CHANNEL_SYSTEM_ALERTS,
)


# Discord embed colors (decimal format)
class Colors:
    """Standard notification colors."""
    SUCCESS = 0x00FF00    # Green
    WARNING = 0xFFA500    # Orange
    ERROR = 0xFF0000      # Red
    INFO = 0x0099FF       # Blue
    SIGNAL = 0x9B59B6     # Purple
    TRADE = 0x2ECC71      # Emerald


@dataclass(frozen=True)
class FieldTemplate:
    """Template for a single message field."""
    name: str
    value_key: str  # Key to look up in payload
    inline: bool = True
    default: Optional[str] = None


@dataclass(frozen=True)
class MessageTemplate:
    """
    Template for rendering a notification message.
    
    Attributes:
        title_pattern: Format string for the title (uses payload keys)
        description_pattern: Format string for the description
        color: Discord embed color
        channel: Target Discord channel for this template
        required_fields: List of payload keys that must be present
        field_templates: Optional field templates for structured data
    """
    title_pattern: str
    description_pattern: str
    color: int
    channel: str
    required_fields: List[str] = field(default_factory=list)
    field_templates: List[FieldTemplate] = field(default_factory=list)


def get_template(event_type: str) -> Optional[MessageTemplate]:
    """Look up a template by event type."""
    return TEMPLATE_REGISTRY.get(event_type)


def list_event_types() -> List[str]:
    """Return all registered event types."""
    return list(TEMPLATE_REGISTRY.keys())


# =============================================================================
# Template Registry
# =============================================================================

TEMPLATE_REGISTRY: Dict[str, MessageTemplate] = {
    # =========================================================================
    # TRADE EXECUTIONS (#trade-executions)
    # =========================================================================
    "trade_opened": MessageTemplate(
        title_pattern="✅ Trade Opened: {symbol}",
        description_pattern="{direction} position opened successfully",
        color=Colors.SUCCESS,
        channel=CHANNEL_TRADE_EXECUTIONS,
        required_fields=["symbol", "direction"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Direction", "direction"),
            FieldTemplate("Entry Price", "entry_price"),
            FieldTemplate("Lot Size", "lot_size"),
            FieldTemplate("Stop Loss", "sl_price"),
            FieldTemplate("Take Profit", "tp_price"),
            FieldTemplate("Ticket #", "ticket"),
            FieldTemplate("Score", "score", default="N/A"),
        ],
    ),
    
    # =========================================================================
    # TRADE FAILURES (#trade-failures)
    # =========================================================================
    "trade_failed": MessageTemplate(
        title_pattern="❌ Trade Failed: {symbol}",
        description_pattern="Order placement failed: {reason}",
        color=Colors.ERROR,
        channel=CHANNEL_TRADE_FAILURES,
        required_fields=["symbol", "reason"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Direction", "direction"),
            FieldTemplate("Attempted Price", "price", default="N/A"),
            FieldTemplate("Lot Size", "lot_size", default="N/A"),
            FieldTemplate("Error Code", "error_code", default="N/A"),
            FieldTemplate("Reason", "reason"),
        ],
    ),
    
    "position_verification_failed": MessageTemplate(
        title_pattern="⚠️ Position Verification Failed: {symbol}",
        description_pattern="Position mismatch detected after order placement",
        color=Colors.ERROR,
        channel=CHANNEL_TRADE_FAILURES,
        required_fields=["symbol", "ticket"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Ticket #", "ticket"),
            FieldTemplate("Expected SL", "expected_sl", default="N/A"),
            FieldTemplate("Actual SL", "actual_sl", default="N/A"),
            FieldTemplate("Expected TP", "expected_tp", default="N/A"),
            FieldTemplate("Actual TP", "actual_tp", default="N/A"),
            FieldTemplate("Issue", "issue", default="Verification failed"),
        ],
    ),
    
    "position_close_failed": MessageTemplate(
        title_pattern="🚨 Position Close Failed: {symbol}",
        description_pattern="Failed to close position after {attempts} attempts",
        color=Colors.ERROR,
        channel=CHANNEL_SYSTEM_ALERTS,
        required_fields=["symbol", "ticket"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Ticket #", "ticket"),
            FieldTemplate("Attempts", "attempts"),
            FieldTemplate("Last Error", "error", default="Unknown"),
        ],
    ),
    
    # =========================================================================
    # TRADE EXECUTIONS (#trade-executions) - continued
    # =========================================================================
    "position_verification_success": MessageTemplate(
        title_pattern="✅ Position Verified: {symbol}",
        description_pattern="Position parameters confirmed correct",
        color=Colors.SUCCESS,
        channel=CHANNEL_TRADE_EXECUTIONS,
        required_fields=["symbol", "ticket"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Ticket #", "ticket"),
            FieldTemplate("Entry Price", "entry_price", default="N/A"),
            FieldTemplate("SL Verified", "sl_price", default="N/A"),
            FieldTemplate("TP Verified", "tp_price", default="N/A"),
            FieldTemplate("Volume", "volume", default="N/A"),
        ],
    ),
    
    # =========================================================================
    # TRADE FAILURES (#trade-failures) - Position closed is a failure
    # =========================================================================
    "position_closed": MessageTemplate(
        title_pattern="🏁 Position Closed: {symbol}",
        description_pattern="Position closed (execution failure)",
        color=Colors.WARNING,
        channel=CHANNEL_TRADE_FAILURES,
        required_fields=["symbol", "ticket"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Ticket #", "ticket"),
            FieldTemplate("Close Price", "close_price", default="N/A"),
            FieldTemplate("P/L", "pnl", default="N/A"),
            FieldTemplate("Reason", "reason", default="N/A"),
        ],
    ),
    
    # =========================================================================
    # TRADE OPPORTUNITIES (#trade-opportunities)
    # =========================================================================
    "signal_detected": MessageTemplate(
        title_pattern="📊 Signal Detected: {symbol}",
        description_pattern="{direction} signal at {signal_time}",
        color=Colors.SIGNAL,
        channel=CHANNEL_TRADE_OPPORTUNITIES,
        required_fields=["symbol", "direction"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Direction", "direction"),
            FieldTemplate("Signal Time", "signal_time"),
            FieldTemplate("Entry Price", "entry_price"),
            FieldTemplate("Stop Loss", "sl_price"),
            FieldTemplate("Take Profit", "tp_price"),
            FieldTemplate("Lot Size", "lot_size"),
            FieldTemplate("AOI Range", "aoi_range"),
            FieldTemplate("AOI TF", "aoi_timeframe"),
            FieldTemplate("Score", "score"),
            FieldTemplate("ATR (1H)", "atr_1h", default="N/A"),
        ],
    ),
    
    # =========================================================================
    # SYSTEM STATUS (#system-status)
    # =========================================================================
    "system_startup": MessageTemplate(
        title_pattern="🚀 System Started",
        description_pattern="Trading system is now online",
        color=Colors.SUCCESS,
        channel=CHANNEL_SYSTEM_STATUS,
        required_fields=[],
        field_templates=[
            FieldTemplate("Mode", "mode", default="live"),
            FieldTemplate("Symbols", "symbol_count", default="N/A"),
            FieldTemplate("MT5 Status", "mt5_status", default="Connected"),
        ],
    ),
    
    "system_shutdown": MessageTemplate(
        title_pattern="🔴 System Shutdown",
        description_pattern="Trading system is shutting down",
        color=Colors.WARNING,
        channel=CHANNEL_SYSTEM_STATUS,
        required_fields=[],
        field_templates=[
            FieldTemplate("Reason", "reason", default="Normal shutdown"),
            FieldTemplate("Active Positions", "active_positions", default="N/A"),
        ],
    ),
    
    "trading_locked": MessageTemplate(
        title_pattern="🔒 Trading Locked",
        description_pattern="Trading has been paused",
        color=Colors.WARNING,
        channel=CHANNEL_SYSTEM_STATUS,
        required_fields=["reason"],
        field_templates=[
            FieldTemplate("Reason", "reason"),
            FieldTemplate("Lock Time", "lock_time", default="N/A"),
        ],
    ),
    
    "trading_unlocked": MessageTemplate(
        title_pattern="🔓 Trading Unlocked",
        description_pattern="Trading has been resumed",
        color=Colors.SUCCESS,
        channel=CHANNEL_SYSTEM_STATUS,
        required_fields=[],
        field_templates=[
            FieldTemplate("Unlock Time", "unlock_time", default="N/A"),
        ],
    ),
    
    # =========================================================================
    # SYSTEM ALERTS (#system-alerts)
    # =========================================================================
    "critical_shutdown": MessageTemplate(
        title_pattern="🛑 CRITICAL: System Shutdown",
        description_pattern="System shutting down due to critical failure",
        color=Colors.ERROR,
        channel=CHANNEL_SYSTEM_ALERTS,
        required_fields=["reason"],
        field_templates=[
            FieldTemplate("Reason", "reason"),
            FieldTemplate("Component", "component", default="Unknown"),
        ],
    ),
    
    "mt5_init_failed": MessageTemplate(
        title_pattern="⚠️ MT5 Initialization Failed",
        description_pattern="Failed to connect to MetaTrader 5",
        color=Colors.ERROR,
        channel=CHANNEL_SYSTEM_ALERTS,
        required_fields=[],
        field_templates=[
            FieldTemplate("Error", "error", default="Connection failed"),
        ],
    ),
    
    "job_failed": MessageTemplate(
        title_pattern="⚠️ Scheduled Job Failed",
        description_pattern="Job '{job_name}' failed with error",
        color=Colors.ERROR,
        channel=CHANNEL_SYSTEM_ALERTS,
        required_fields=["job_name", "error"],
        field_templates=[
            FieldTemplate("Job Name", "job_name"),
            FieldTemplate("Error", "error"),
            FieldTemplate("Timeframe", "timeframe", default="N/A"),
        ],
    ),
}
