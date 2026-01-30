"""
Notification Infrastructure Module

A template-based notification system for sending Discord webhooks.
Provides a single public interface: NotificationManager.notify()

Usage:
    from notifications import NotificationManager, load_config_from_env
    
    config = load_config_from_env()
    manager = NotificationManager(config)
    
    # Send a notification
    manager.notify("signal_detected", {
        "symbol": "EURUSD",
        "direction": "BUY",
        "timeframe": "1H",
    })

Configuration:
    Set DISCORD_WEBHOOK_URL in environment variables or pass a config object.
    
Event Types:
    - signal_detected: Trading signal found
    - trade_opened: Trade executed successfully
    - trade_closed: Trade closed (SL/TP/manual)
    - trade_failed: Trade execution failed
    - system_startup: System started
    - system_shutdown: System stopped
    - system_error: System error occurred
    - generic: Fallback for unknown events
"""

from .config import (
    NotificationConfig,
    load_config_from_env,
    create_config,
)
from .manager import NotificationManager
from .templates import list_event_types


__all__ = [
    "NotificationManager",
    "NotificationConfig",
    "load_config_from_env",
    "create_config",
    "list_event_types",
]
