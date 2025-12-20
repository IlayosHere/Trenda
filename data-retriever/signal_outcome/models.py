"""Data models for signal outcome computation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PendingSignal:
    """A signal awaiting outcome computation."""

    id: int
    symbol: str
    signal_time: datetime
    direction: str
    entry_price: float
    atr_1h: float
    # AOI data for SL/TP computation
    aoi_low: float
    aoi_high: float
    aoi_effective_sl_distance_price: float


@dataclass(frozen=True)
class CheckpointReturn:
    """A single checkpoint return measurement."""
    
    bars_after: int       # e.g., 3, 6, 12, 24, 48, 72, 96, 120, 144, 168
    return_atr: float     # Return in ATR units at this checkpoint


@dataclass(frozen=True)
class OutcomeData:
    """Computed outcome for a signal (without checkpoint returns)."""

    # Window info
    window_bars: int
    # MFE/MAE
    mfe_atr: float
    mae_atr: float
    bars_to_mfe: int
    bars_to_mae: int
    first_extreme: str
    # SL/TP hits (bars to hit or None)
    bars_to_aoi_sl_hit: int | None
    bars_to_r_1: int | None
    bars_to_r_1_5: int | None
    bars_to_r_2: int | None
    aoi_rr_outcome: str


@dataclass(frozen=True)
class OutcomeWithCheckpoints:
    """Full outcome data including checkpoint returns."""
    
    outcome: OutcomeData
    checkpoint_returns: list[CheckpointReturn]
