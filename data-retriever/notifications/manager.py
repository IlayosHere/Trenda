"""
NotificationManager - Main entry point for the notification system.

Orchestrates template lookup, rendering, and Discord delivery.
Routes notifications to the appropriate Discord channel.
"""

import logging
from typing import Dict, Optional

from .config import NotificationConfig
from .templates import get_template, MessageTemplate, TEMPLATE_REGISTRY
from .renderer import render_template, validate_required_fields, get_missing_fields
from .discord_sender import send_message


logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Main notification manager for sending Discord notifications.
    
    This is the single public entry point for the notification system.
    All notifications are best-effort: failures are logged but never
    raised to callers.
    
    Notifications are routed to the appropriate Discord channel based
    on the event type's template configuration.
    
    Usage:
        config = load_config_from_env()
        manager = NotificationManager(config)
        manager.notify("signal_detected", {"symbol": "EURUSD", ...})
    """
    
    def __init__(self, config: NotificationConfig):
        """
        Initialize the notification manager.
        
        Args:
            config: Notification configuration
        """
        self._config = config
        self._log_startup()
    
    def _log_startup(self) -> None:
        """Log startup configuration status."""
        if not self._config.enabled:
            logger.info("NotificationManager initialized (notifications disabled)")
        elif not self._config.webhook_urls:
            logger.warning("NotificationManager: no webhook URLs configured")
        else:
            channels = list(self._config.webhook_urls.keys())
            logger.info(f"NotificationManager initialized with channels: {channels}")
    
    def notify(self, event_type: str, payload: Dict) -> None:
        """
        Send a notification for the given event type.
        
        This is the single public method for all notifications.
        Failures are logged but never raised.
        
        The notification is routed to the appropriate Discord channel
        based on the template's channel configuration.
        
        Args:
            event_type: The type of event (maps to a template)
            payload: Dictionary of values to render into the template
        """
        if not self._config.enabled:
            logger.debug(f"Notification skipped (disabled): {event_type}")
            return
        
        try:
            self._send_notification(event_type, payload)
        except Exception as e:
            # Catch-all: never raise to callers
            logger.error(
                f"Notification failed unexpectedly: {event_type} - "
                f"{type(e).__name__}: {e}"
            )
    
    def _send_notification(self, event_type: str, payload: Dict) -> None:
        """Internal notification logic."""
        # Look up template
        template = self._get_template(event_type)
        if template is None:
            logger.warning(f"No template for event type: {event_type}")
            return
        
        # Get webhook URL for the template's channel
        webhook_url = self._config.get_webhook_url(template.channel)
        if not webhook_url:
            logger.debug(
                f"No webhook configured for channel '{template.channel}' "
                f"(event: {event_type})"
            )
            return
        
        # Validate required fields
        if not validate_required_fields(template, payload):
            missing = get_missing_fields(template, payload)
            logger.warning(
                f"Missing required fields for {event_type}: {missing}"
            )
            # Continue anyway with partial data
        
        # Render message
        message = render_template(template, payload)
        
        # Send via Discord
        success = send_message(
            webhook_url,
            message,
            self._config.timeout,
        )
        
        if success:
            logger.debug(f"Notification sent: {event_type} -> {template.channel}")
        else:
            logger.warning(f"Notification delivery failed: {event_type}")
    
    def _get_template(self, event_type: str) -> Optional[MessageTemplate]:
        """
        Get template for event type.
        
        Args:
            event_type: The event type to look up
            
        Returns:
            MessageTemplate or None if not found
        """
        return get_template(event_type)
    
    @property
    def is_enabled(self) -> bool:
        """Check if the notification manager is enabled."""
        return self._config.enabled
    
    @property
    def configured_channels(self) -> list:
        """Return list of configured channel names."""
        return list(self._config.webhook_urls.keys())
