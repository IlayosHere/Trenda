"""
Discord webhook transport layer.

Handles conversion to Discord embed format and HTTP delivery.
Uses only stdlib to avoid external dependencies.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

from .types import NormalizedMessage, DiscordEmbed


logger = logging.getLogger(__name__)


def to_discord_embed(message: NormalizedMessage) -> DiscordEmbed:
    """
    Convert a normalized message to a Discord embed structure.
    
    Args:
        message: The normalized message
        
    Returns:
        Discord embed ready for serialization
    """
    fields = [
        {
            "name": f.name,
            "value": f.value,
            "inline": f.inline,
        }
        for f in message.fields
    ]
    
    timestamp = None
    if message.timestamp:
        timestamp = message.timestamp.isoformat()
    
    footer = None
    if message.footer:
        footer = {"text": message.footer}
    
    return DiscordEmbed(
        title=message.title,
        description=message.description,
        color=message.color,
        fields=fields,
        timestamp=timestamp,
        footer=footer,
    )


def build_webhook_payload(embed: DiscordEmbed) -> dict:
    """
    Build the full webhook payload with embed.
    
    Args:
        embed: The Discord embed
        
    Returns:
        Full webhook payload dictionary
    """
    return {
        "embeds": [embed.to_dict()]
    }


def send_webhook(
    webhook_url: str,
    embed: DiscordEmbed,
    timeout: float = 5.0,
) -> bool:
    """
    Send a Discord webhook with the given embed.
    
    This is a best-effort operation:
    - Uses timeout to prevent blocking
    - Catches all exceptions
    - Never raises to callers
    
    Args:
        webhook_url: The Discord webhook URL
        embed: The embed to send
        timeout: HTTP timeout in seconds
        
    Returns:
        True if successful, False otherwise
    """
    if not webhook_url:
        logger.warning("Discord webhook URL is not configured")
        return False
    
    try:
        payload = build_webhook_payload(embed)
        data = json.dumps(payload).encode('utf-8')
        
        request = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Trenda-Notification/1.0",
            },
            method="POST",
        )
        
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            if status in (200, 204):
                logger.debug(f"Discord webhook sent successfully: {status}")
                return True
            else:
                logger.warning(f"Discord webhook unexpected status: {status}")
                return False
                
    except urllib.error.HTTPError as e:
        logger.error(f"Discord webhook HTTP error: {e.code} - {e.reason}")
        return False
        
    except urllib.error.URLError as e:
        logger.error(f"Discord webhook URL error: {e.reason}")
        return False
        
    except TimeoutError:
        logger.error("Discord webhook timed out")
        return False
        
    except Exception as e:
        logger.error(f"Discord webhook unexpected error: {type(e).__name__}: {e}")
        return False


def send_message(
    webhook_url: str,
    message: NormalizedMessage,
    timeout: float = 5.0,
) -> bool:
    """
    Send a normalized message via Discord webhook.
    
    Convenience function that converts and sends in one call.
    
    Args:
        webhook_url: The Discord webhook URL
        message: The normalized message to send
        timeout: HTTP timeout in seconds
        
    Returns:
        True if successful, False otherwise
    """
    embed = to_discord_embed(message)
    return send_webhook(webhook_url, embed, timeout)
