"""
Configuration for the notification system.

Supports loading from environment variables or direct configuration.
Supports multiple Discord channels via separate webhook URLs.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


# Channel name constants
CHANNEL_TRADE_EXECUTIONS = "trade_executions"
CHANNEL_TRADE_FAILURES = "trade_failures"
CHANNEL_TRADE_OPPORTUNITIES = "trade_opportunities"
CHANNEL_SYSTEM_STATUS = "system_status"
CHANNEL_SYSTEM_ALERTS = "system_alerts"


@dataclass
class NotificationConfig:
    """
    Configuration for the notification system.
    
    Attributes:
        webhook_urls: Dict mapping channel name to webhook URL
        timeout: HTTP timeout in seconds
        enabled: Whether notifications are enabled
    """
    webhook_urls: Dict[str, str] = field(default_factory=dict)
    timeout: float = 5.0
    enabled: bool = True
    
    def get_webhook_url(self, channel: str) -> Optional[str]:
        """Get webhook URL for a specific channel."""
        return self.webhook_urls.get(channel)
    
    def is_valid(self) -> bool:
        """Check if configuration is valid (has at least one webhook)."""
        return self.enabled and bool(self.webhook_urls)
    
    def is_channel_configured(self, channel: str) -> bool:
        """Check if a specific channel has a webhook configured."""
        return bool(self.webhook_urls.get(channel))


def load_config_from_env() -> NotificationConfig:
    """
    Load notification configuration from environment variables.
    
    Environment variables:
        DISCORD_WEBHOOK_TRADE_EXECUTIONS: Webhook for #trade-executions
        DISCORD_WEBHOOK_TRADE_FAILURES: Webhook for #trade-failures
        DISCORD_WEBHOOK_TRADE_OPPORTUNITIES: Webhook for #trade-opportunities
        DISCORD_WEBHOOK_SYSTEM_STATUS: Webhook for #system-status
        DISCORD_WEBHOOK_SYSTEM_ALERTS: Webhook for #system-alerts
        DISCORD_WEBHOOK_TIMEOUT: Optional timeout (default: 5.0)
        NOTIFICATIONS_ENABLED: Optional enabled flag (default: true)
        
    Returns:
        NotificationConfig loaded from environment
    """
    webhook_urls = {}
    
    # Map environment variable names to channel names
    channel_env_map = {
        CHANNEL_TRADE_EXECUTIONS: "DISCORD_WEBHOOK_TRADE_EXECUTIONS",
        CHANNEL_TRADE_FAILURES: "DISCORD_WEBHOOK_TRADE_FAILURES",
        CHANNEL_TRADE_OPPORTUNITIES: "DISCORD_WEBHOOK_TRADE_OPPORTUNITIES",
        CHANNEL_SYSTEM_STATUS: "DISCORD_WEBHOOK_SYSTEM_STATUS",
        CHANNEL_SYSTEM_ALERTS: "DISCORD_WEBHOOK_SYSTEM_ALERTS",
    }
    
    for channel, env_var in channel_env_map.items():
        url = os.getenv(env_var, "")
        if url:
            webhook_urls[channel] = url
    
    timeout_str = os.getenv("DISCORD_WEBHOOK_TIMEOUT", "5.0")
    try:
        timeout = float(timeout_str)
    except ValueError:
        timeout = 5.0
    
    enabled_str = os.getenv("NOTIFICATIONS_ENABLED", "true").lower()
    enabled = enabled_str in ("true", "1", "yes", "on")
    
    return NotificationConfig(
        webhook_urls=webhook_urls,
        timeout=timeout,
        enabled=enabled,
    )


def create_config(
    webhook_urls: Dict[str, str],
    timeout: float = 5.0,
    enabled: bool = True,
) -> NotificationConfig:
    """
    Create a notification configuration directly.
    
    Args:
        webhook_urls: Dict mapping channel name to webhook URL
        timeout: HTTP timeout in seconds
        enabled: Whether notifications are enabled
        
    Returns:
        NotificationConfig instance
    """
    return NotificationConfig(
        webhook_urls=webhook_urls,
        timeout=timeout,
        enabled=enabled,
    )
