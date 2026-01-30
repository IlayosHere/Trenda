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
        "signal_time": "2026-01-30 09:00",
        ...
    })

Configuration:
    Set webhook URLs in environment variables:
    - DISCORD_WEBHOOK_TRADE_EXECUTIONS
    - DISCORD_WEBHOOK_TRADE_FAILURES
    - DISCORD_WEBHOOK_TRADE_OPPORTUNITIES
    - DISCORD_WEBHOOK_SYSTEM_STATUS
    - DISCORD_WEBHOOK_SYSTEM_ALERTS
    
Event Types (by channel):
    #trade-executions:
        - trade_opened
        - position_verification_success
    #trade-failures:
        - trade_failed
        - position_verification_failed
        - position_closed
    #trade-opportunities:
        - signal_detected
    #system-status:
        - system_startup
        - system_shutdown
        - trading_locked
        - trading_unlocked
    #system-alerts:
        - position_close_failed
        - critical_shutdown
        - mt5_init_failed
        - job_failed
"""

from .config import (
    NotificationConfig,
    load_config_from_env,
    create_config,
    CHANNEL_TRADE_EXECUTIONS,
    CHANNEL_TRADE_FAILURES,
    CHANNEL_TRADE_OPPORTUNITIES,
    CHANNEL_SYSTEM_STATUS,
    CHANNEL_SYSTEM_ALERTS,
)
from .manager import NotificationManager
from .templates import list_event_types


__all__ = [
    # Main API
    "NotificationManager",
    "NotificationConfig",
    "load_config_from_env",
    "create_config",
    "list_event_types",
    # Channel constants
    "CHANNEL_TRADE_EXECUTIONS",
    "CHANNEL_TRADE_FAILURES",
    "CHANNEL_TRADE_OPPORTUNITIES",
    "CHANNEL_SYSTEM_STATUS",
    "CHANNEL_SYSTEM_ALERTS",
]


# Global notification manager instance (lazily initialized)
_notification_manager: NotificationManager = None


def get_notification_manager() -> NotificationManager:
    """
    Get or create the global notification manager.
    
    This provides a convenient singleton pattern for accessing
    the notification manager throughout the application.
    
    Returns:
        The global NotificationManager instance
    """
    global _notification_manager
    if _notification_manager is None:
        config = load_config_from_env()
        _notification_manager = NotificationManager(config)
    return _notification_manager


def notify(event_type: str, payload: dict) -> None:
    """
    Convenience function to send a notification using the global manager.
    
    Args:
        event_type: The type of event
        payload: Dictionary of values for the template
    """
    get_notification_manager().notify(event_type, payload)
