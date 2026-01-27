from typing import NamedTuple

class SafeguardStatus(NamedTuple):
    """Result of a safeguard check."""
    is_allowed: bool
    reason: str
