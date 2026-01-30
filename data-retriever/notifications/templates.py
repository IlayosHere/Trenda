"""
Template definitions for notification messages.

Each event type maps to a MessageTemplate that defines how to render
the notification message from a payload dictionary.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


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
        required_fields: List of payload keys that must be present
        field_templates: Optional field templates for structured data
    """
    title_pattern: str
    description_pattern: str
    color: int
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
    # Trading signals
    "signal_detected": MessageTemplate(
        title_pattern="📊 Signal Detected: {symbol}",
        description_pattern="{direction} signal on {timeframe}",
        color=Colors.SIGNAL,
        required_fields=["symbol", "direction", "timeframe"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Direction", "direction"),
            FieldTemplate("Timeframe", "timeframe"),
            FieldTemplate("Score", "score", default="N/A"),
        ],
    ),
    
    # Trade execution
    "trade_opened": MessageTemplate(
        title_pattern="✅ Trade Opened: {symbol}",
        description_pattern="{direction} position opened at {price}",
        color=Colors.SUCCESS,
        required_fields=["symbol", "direction", "price"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Direction", "direction"),
            FieldTemplate("Entry Price", "price"),
            FieldTemplate("Stop Loss", "sl", default="N/A"),
            FieldTemplate("Take Profit", "tp", default="N/A"),
            FieldTemplate("Lot Size", "lot_size", default="N/A"),
        ],
    ),
    
    "trade_closed": MessageTemplate(
        title_pattern="🏁 Trade Closed: {symbol}",
        description_pattern="Position closed: {outcome}",
        color=Colors.INFO,
        required_fields=["symbol", "outcome"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Outcome", "outcome"),
            FieldTemplate("Close Price", "close_price", default="N/A"),
            FieldTemplate("P/L", "pnl", default="N/A"),
        ],
    ),
    
    "trade_failed": MessageTemplate(
        title_pattern="❌ Trade Failed: {symbol}",
        description_pattern="Order failed: {reason}",
        color=Colors.ERROR,
        required_fields=["symbol", "reason"],
        field_templates=[
            FieldTemplate("Symbol", "symbol"),
            FieldTemplate("Reason", "reason"),
            FieldTemplate("Error Code", "error_code", default="N/A"),
        ],
    ),
    
    # System events
    "system_startup": MessageTemplate(
        title_pattern="🚀 System Started",
        description_pattern="Trading system is now online",
        color=Colors.SUCCESS,
        required_fields=[],
        field_templates=[
            FieldTemplate("Version", "version", default="N/A"),
            FieldTemplate("Environment", "environment", default="production"),
        ],
    ),
    
    "system_shutdown": MessageTemplate(
        title_pattern="🔴 System Shutdown",
        description_pattern="Trading system is shutting down",
        color=Colors.WARNING,
        required_fields=[],
        field_templates=[
            FieldTemplate("Reason", "reason", default="Normal shutdown"),
        ],
    ),
    
    "system_error": MessageTemplate(
        title_pattern="⚠️ System Error",
        description_pattern="{message}",
        color=Colors.ERROR,
        required_fields=["message"],
        field_templates=[
            FieldTemplate("Component", "component", default="Unknown"),
            FieldTemplate("Error Type", "error_type", default="Unknown"),
        ],
    ),
    
    # Fallback for unknown events
    "generic": MessageTemplate(
        title_pattern="📢 Notification",
        description_pattern="{message}",
        color=Colors.INFO,
        required_fields=["message"],
    ),
}
