from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class AOISettings:
    """Container for AOI rules tied to a specific timeframe."""

    timeframe: str
    timeframe_hours: int
    min_touches: int
    min_range_pips: float
    min_swing_gap_bars: int
    overlap_tolerance_pips: float
    max_age_days: int
    max_zones_per_symbol: int
    min_height_ratio: float
    min_height_pips_floor: float
    max_height_ratio: float
    max_height_min_pips: float
    max_height_max_pips: float
    bound_tolerance_ratio: float
    directional_extension_ratio: float
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
        min_range_pips=30,
        min_swing_gap_bars=3,
        overlap_tolerance_pips=2.0,
        max_age_days=2,
        max_zones_per_symbol=3,
        min_height_ratio=0.05,
        min_height_pips_floor=8,
        max_height_ratio=0.15,
        max_height_min_pips=20,
        max_height_max_pips=40,
        bound_tolerance_ratio=0.8,
        directional_extension_ratio=0.35,
        alignment_weight=1.25,
        trend_alignment_timeframes=("4H", "1D", "1W"),
    ),
    "1D": AOISettings(
        timeframe="1D",
        timeframe_hours=24,
        min_touches=3,
        min_range_pips=60,
        min_swing_gap_bars=1,
        overlap_tolerance_pips=8.0,
        max_age_days=8,
        max_zones_per_symbol=3,
        min_height_ratio=0.1,
        min_height_pips_floor=16,
        max_height_ratio=0.35,
        max_height_min_pips=30,
        max_height_max_pips=100,
        bound_tolerance_ratio=0.35,
        directional_extension_ratio=0.35,
        alignment_weight=1.25,
        trend_alignment_timeframes=("4H", "1D", "1W"),
    )
}
