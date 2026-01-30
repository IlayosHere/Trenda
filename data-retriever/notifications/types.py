"""
Type definitions for the notification system.

Defines normalized internal message structures that are transport-agnostic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class MessageField:
    """A single field in a notification message."""
    name: str
    value: str
    inline: bool = True


@dataclass(frozen=True)
class NormalizedMessage:
    """
    Transport-agnostic internal message structure.
    
    This is the canonical representation of a notification message
    before it's converted to a specific transport format (e.g., Discord).
    """
    title: str
    description: str
    color: int
    fields: List[MessageField] = field(default_factory=list)
    timestamp: Optional[datetime] = None
    footer: Optional[str] = None


@dataclass(frozen=True)
class DiscordEmbed:
    """
    Discord-specific embed structure for webhook payloads.
    
    Matches Discord's embed object specification.
    """
    title: str
    description: str
    color: int
    fields: List[dict] = field(default_factory=list)
    timestamp: Optional[str] = None
    footer: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to Discord API payload format."""
        payload = {
            "title": self.title,
            "description": self.description,
            "color": self.color,
        }
        
        if self.fields:
            payload["fields"] = self.fields
        
        if self.timestamp:
            payload["timestamp"] = self.timestamp
        
        if self.footer:
            payload["footer"] = self.footer
        
        return payload
