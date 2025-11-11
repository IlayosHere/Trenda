"""Pipeline utilities that transform raw swings into AOI zones."""

from typing import Dict, List

from .candidates import find_zone_candidates
from .filters import (
    filter_old_zones_by_bars,
    filter_overlapping_zones,
    filter_zones_by_bounds,
    merge_nearby_zones,
)
from .models import AOIContext


def generate_aoi_zones(swings: List, last_bar_idx: int, context: AOIContext) -> List[Dict[str, float]]:
    """Run the AOI candidate pipeline and return serializable zone dicts."""
    if not swings:
        return []

    candidates = find_zone_candidates(swings, last_bar_idx, context)
    bounded = filter_zones_by_bounds(candidates, context)
    merged = merge_nearby_zones(bounded, context)
    recent = filter_old_zones_by_bars(merged, last_bar_idx)
    non_overlapping = filter_overlapping_zones(recent, context)

    return [
        {
            "lower_bound": zone.lower_bound,
            "upper_bound": zone.upper_bound,
            "height": zone.height,
            "touches": zone.touches,
            "score": zone.score,
            "last_swing_idx": zone.last_swing_idx,
        }
        for zone in non_overlapping
    ]


__all__ = ["generate_aoi_zones"]
