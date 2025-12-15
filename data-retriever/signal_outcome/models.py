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
class OutcomeData:
    """Computed outcome for a signal."""

    # Window info
    window_bars: int
    # MFE/MAE
    mfe_atr: float
    mae_atr: float
    bars_to_mfe: int
    bars_to_mae: int
    first_extreme: str
    # Checkpoint returns
    return_after_3: float | None
    return_after_6: float | None
    return_after_12: float | None
    return_after_24: float | None
    return_end_window: float | None
    # SL/TP hits
    bars_to_aoi_sl_hit: int | None
    bars_to_r_1: int | None
    bars_to_r_1_5: int | None
    bars_to_r_2: int | None
    aoi_rr_outcome: str
