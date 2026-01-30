"""
Configuration for the notification system.

Supports loading from environment variables or direct configuration.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class NotificationConfig:
    """
    Configuration for the notification system.
    
    Attributes:
        webhook_url: Discord webhook URL
        timeout: HTTP timeout in seconds
        enabled: Whether notifications are enabled
    """
    webhook_url: str
    timeout: float = 5.0
    enabled: bool = True
    
    def is_valid(self) -> bool:
        """Check if configuration is valid for sending notifications."""
        return self.enabled and bool(self.webhook_url)


def load_config_from_env() -> NotificationConfig:
    """
    Load notification configuration from environment variables.
    
    Environment variables:
        DISCORD_WEBHOOK_URL: Required webhook URL
        DISCORD_WEBHOOK_TIMEOUT: Optional timeout (default: 5.0)
        NOTIFICATIONS_ENABLED: Optional enabled flag (default: true)
        
    Returns:
        NotificationConfig loaded from environment
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    timeout_str = os.getenv("DISCORD_WEBHOOK_TIMEOUT", "5.0")
    try:
        timeout = float(timeout_str)
    except ValueError:
        timeout = 5.0
    
    enabled_str = os.getenv("NOTIFICATIONS_ENABLED", "true").lower()
    enabled = enabled_str in ("true", "1", "yes", "on")
    
    return NotificationConfig(
        webhook_url=webhook_url,
        timeout=timeout,
        enabled=enabled,
    )


def create_config(
    webhook_url: str,
    timeout: float = 5.0,
    enabled: bool = True,
) -> NotificationConfig:
    """
    Create a notification configuration directly.
    
    Args:
        webhook_url: Discord webhook URL
        timeout: HTTP timeout in seconds
        enabled: Whether notifications are enabled
        
    Returns:
        NotificationConfig instance
    """
    return NotificationConfig(
        webhook_url=webhook_url,
        timeout=timeout,
        enabled=enabled,
    )
