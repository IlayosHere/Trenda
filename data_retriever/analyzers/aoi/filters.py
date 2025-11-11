"""Filtering helpers for AOI zone candidates."""

from typing import List

from data_retriever.utils.forex import pips_to_price

from .config import AOI_MAX_AGE_BARS, AOI_OVERLAP_TOLERANCE_PIPS
from .models import AOIContext, AOIZoneCandidate


def filter_zones_by_bounds(zones: List[AOIZoneCandidate], context: AOIContext) -> List[AOIZoneCandidate]:
    low_allowed = context.base_low - context.tolerance_price
    high_allowed = context.base_high + context.tolerance_price
    return [
        z
        for z in zones
        if low_allowed <= z.lower_bound <= high_allowed
        and low_allowed <= z.upper_bound <= high_allowed
        and z.height <= context.max_height_price
    ]


def merge_nearby_zones(zones: List[AOIZoneCandidate], context: AOIContext) -> List[AOIZoneCandidate]:
    if not zones:
        return []
    zones = sorted(zones, key=lambda z: z.lower_bound)
    merged: List[AOIZoneCandidate] = [zones[0]]
    tolerance = pips_to_price(AOI_OVERLAP_TOLERANCE_PIPS, context.pip_size)

    for zone in zones[1:]:
        last = merged[-1]
        if zone.lower_bound <= last.upper_bound + tolerance:
            new_lower = min(last.lower_bound, zone.lower_bound)
            new_upper = max(last.upper_bound, zone.upper_bound)
            new_height = new_upper - new_lower
            if new_height <= context.max_height_price:
                merged[-1] = AOIZoneCandidate(
                    lower_bound=new_lower,
                    upper_bound=new_upper,
                    height=new_height,
                    touches=last.touches + zone.touches,
                    score=max(last.score, zone.score),
                    last_swing_idx=max(last.last_swing_idx, zone.last_swing_idx),
                )
            else:
                merged.append(zone)
        else:
            merged.append(zone)
    return merged


def filter_old_zones_by_bars(zones: List[AOIZoneCandidate], last_bar_idx: int) -> List[AOIZoneCandidate]:
    cutoff = last_bar_idx - AOI_MAX_AGE_BARS
    return [z for z in zones if z.last_swing_idx >= cutoff]


def filter_overlapping_zones(zones: List[AOIZoneCandidate], context: AOIContext) -> List[AOIZoneCandidate]:
    if not zones:
        return []
    tolerance = pips_to_price(AOI_OVERLAP_TOLERANCE_PIPS, context.pip_size)
    zones = sorted(zones, key=lambda z: z.score, reverse=True)

    selected: List[AOIZoneCandidate] = []
    for zone in zones:
        overlap = any(
            not (zone.upper_bound < existing.lower_bound - tolerance or zone.lower_bound > existing.upper_bound + tolerance)
            for existing in selected
        )
        if not overlap:
            selected.append(zone)
    return sorted(selected, key=lambda z: z.lower_bound)


__all__ = [
    "filter_zones_by_bounds",
    "merge_nearby_zones",
    "filter_old_zones_by_bars",
    "filter_overlapping_zones",
]
