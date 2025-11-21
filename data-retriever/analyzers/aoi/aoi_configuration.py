from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class AOISettings:
    """Container for AOI rules tied to a specific timeframe."""

    timeframe: str
    timeframe_hours: int
    min_touches: int
    min_swing_gap_bars: int
    overlap_tolerance_pips: float
    max_age_days: int
    max_zones_per_symbol: int
    min_height_atr_multiplier: float
    min_height_pips_floor: float
    max_heihgt_pips_floor: float
    max_height_atr_multiplier: float
    alignment_weight: float
    trend_alignment_timeframes: Tuple[str, ...]

    @property
    def max_age_bars(self) -> int:
        """Maximum bar age derived from the timeframe size."""
        if self.timeframe_hours <= 0:
            return 0
        return int((self.max_age_days * 24) / self.timeframe_hours)


AOI_CONFIGS: Dict[str, AOISettings] = {
    "4H": AOISettings(
        timeframe="4H",
        timeframe_hours=4,
        min_touches=3,
        min_swing_gap_bars=6,
        overlap_tolerance_pips=2.0,
        max_age_days=5,
        max_zones_per_symbol=3,
        min_height_atr_multiplier=0.2,
        min_height_pips_floor=10,
        max_heihgt_pips_floor=100,
        max_height_atr_multiplier=0.7,
        alignment_weight=1.5,
        trend_alignment_timeframes=("4H", "1D", "1W")
    ),
    "1D": AOISettings(
        timeframe="1D",
        timeframe_hours=24,
        min_touches=3,
        min_swing_gap_bars=3,
        overlap_tolerance_pips=4.0,
        max_age_days=25,
        max_zones_per_symbol=2,
        min_height_atr_multiplier=0.25,
        min_height_pips_floor=20,
        max_heihgt_pips_floor=150,
        max_height_atr_multiplier=0.8,
        alignment_weight=1.25,
        trend_alignment_timeframes=("4H", "1D", "1W")
    ),
    "1W": AOISettings(
        timeframe="1W",
        timeframe_hours=168,
        min_touches=2,
        min_swing_gap_bars=2,
        overlap_tolerance_pips=10.0,
        max_age_days=120,
        max_zones_per_symbol=2,
        min_height_atr_multiplier=0.15,
        min_height_pips_floor=20,
        max_heihgt_pips_floor=150,
        max_height_atr_multiplier=0.5,
        alignment_weight=1.10,
        trend_alignment_timeframes=("4H", "1D", "1W")
    )
}
