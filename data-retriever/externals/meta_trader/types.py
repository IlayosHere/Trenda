from typing import NamedTuple


class CloseAttemptStatus(NamedTuple):
    """Result of a single position closure attempt."""
    success: bool
    should_retry: bool
