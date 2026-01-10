"""Data models for signal outcome computation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PendingSignal:
    """A signal awaiting outcome computation."""

    id: int
    symbol: str
    signal_time: datetime
    direction: str
    entry_price: float
    atr_1h: float
    # AOI bounds for fallback SL calculation
    aoi_low: float
    aoi_high: float
    # SL distance for exit detection (may be None for legacy signals)
    sl_distance_atr: Optional[float]


@dataclass(frozen=True)
class OutcomeData:
    """Computed outcome for a signal (96 bar window)."""

    # Window info
    window_bars: int
    # MFE/MAE
    mfe_atr: float
    mae_atr: float
    bars_to_mfe: int
    bars_to_mae: int
    first_extreme: str
    # Checkpoint returns
    return_after_48: Optional[float]
    return_after_72: Optional[float]
    return_after_96: Optional[float]
    # Exit tracking
    exit_reason: str  # SL, TP, TIMEOUT
    bars_to_exit: Optional[int]  # Bar number when SL or TP was hit
