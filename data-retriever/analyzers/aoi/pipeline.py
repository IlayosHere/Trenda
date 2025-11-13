from dataclasses import dataclass
from typing import Dict, List

from utils.forex import pips_to_price

from .context import AOIContext


@dataclass
class AOIZoneCandidate:
    lower_bound: float
    upper_bound: float
    height: float
    touches: int
    score: float
    last_swing_idx: int


def generate_aoi_zones(
    swings: List, last_bar_idx: int, context: AOIContext
) -> List[Dict[str, float]]:
    """Full AOI generation pipeline that returns lightweight zone dicts."""

    if not swings:
        return []

    candidates = _find_zone_candidates(swings, last_bar_idx, context)
    bounded = _filter_zones_by_bounds(candidates, context)
    merged = _merge_nearby_zones(bounded, context)
    recent = _filter_old_zones_by_bars(merged, last_bar_idx, context)
    non_overlapping = _filter_overlapping_zones(recent, context)

    return [
        {
            "lower_bound": z.lower_bound,
            "upper_bound": z.upper_bound,
            "height": z.height,
            "touches": z.touches,
            "score": z.score,
            "last_swing_idx": z.last_swing_idx,
        }
        for z in non_overlapping
    ]


def _find_zone_candidates(
    swings: List, last_bar_idx: int, context: AOIContext
) -> List[AOIZoneCandidate]:
    """Identify AOI candidates from swing clustering."""

    pairs: List[tuple[int, float]] = [(int(s[0]), float(s[1])) for s in swings]
    price_sorted: List[tuple[int, float]] = sorted(pairs, key=lambda x: x[1])

    candidates: Dict[tuple, AOIZoneCandidate] = {}
    settings = context.settings
    total = len(price_sorted)

    for i in range(total):
        lower_idx, lower_price = price_sorted[i]

        for j in range(i + settings.min_touches - 1, total):
            upper_idx, upper_price = price_sorted[j]
            height = upper_price - lower_price

            if not _is_zone_within_extended_bounds(
                lower_price, upper_price, context
            ):
                break

            if height < context.min_height_price or height > context.max_height_price:
                continue

            mid_indices = [
                idx for (idx, price) in pairs if lower_price <= price <= upper_price
            ]
            if len(mid_indices) < settings.min_touches:
                continue
            if not _has_sufficient_spacing(mid_indices, settings.min_swing_gap_bars):
                continue

            last_idx = max(mid_indices)
            base_score = _calculate_base_zone_score(
                lower_price,
                upper_price,
                height,
                len(mid_indices),
                last_idx,
                last_bar_idx,
                context,
            )

            key = (
                round(lower_price / context.pip_size, 5),
                round(upper_price / context.pip_size, 5),
            )
            existing = candidates.get(key)
            if not existing or base_score > existing.score:
                candidates[key] = AOIZoneCandidate(
                    lower_bound=lower_price,
                    upper_bound=upper_price,
                    height=height,
                    touches=len(mid_indices),
                    score=base_score,
                    last_swing_idx=last_idx,
                )

    return list(candidates.values())


def _calculate_base_zone_score(
    lower: float,
    upper: float,
    height: float,
    touches: int,
    last_idx: int,
    last_bar_idx: int,
    context: AOIContext,
) -> float:
    """Base AOI score before trend-direction bias."""

    density = (touches ** 1.2) / max(height, 1e-6)

    bars_since_last = last_bar_idx - last_idx
    recency_factor = 1 / (1 + (bars_since_last / 100.0))

    zone_mid = (upper + lower) / 2.0
    range_mid = (context.base_high + context.base_low) / 2.0
    range_half = max((context.base_high - context.base_low) / 2.0, 1e-9)
    distance_from_mid = abs(zone_mid - range_mid)
    extremity_factor = 1 + (distance_from_mid / range_half) * 0.2

    return density * recency_factor * extremity_factor


def _has_sufficient_spacing(indices: List[int], min_gap_bars: int) -> bool:
    """Ensure swing touches are spaced out in time."""

    return all(indices[i] - indices[i - 1] >= min_gap_bars for i in range(1, len(indices)))


def _filter_zones_by_bounds(
    zones: List[AOIZoneCandidate], context: AOIContext
) -> List[AOIZoneCandidate]:
    low_allowed = context.base_low - context.tolerance_price
    high_allowed = context.base_high + context.tolerance_price
    return [
        z
        for z in zones
        if low_allowed <= z.lower_bound <= high_allowed
        and low_allowed <= z.upper_bound <= high_allowed
        and z.height <= context.max_height_price
    ]


def _merge_nearby_zones(
    zones: List[AOIZoneCandidate], context: AOIContext
) -> List[AOIZoneCandidate]:
    if not zones:
        return []
    zones = sorted(zones, key=lambda z: z.lower_bound)
    merged: List[AOIZoneCandidate] = [zones[0]]
    tol = pips_to_price(context.settings.overlap_tolerance_pips, context.pip_size)

    for zone in zones[1:]:
        last = merged[-1]
        if zone.lower_bound <= last.upper_bound + tol:
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


def _filter_old_zones_by_bars(
    zones: List[AOIZoneCandidate], last_bar_idx: int, context: AOIContext
) -> List[AOIZoneCandidate]:
    cutoff = last_bar_idx - context.settings.max_age_bars
    return [z for z in zones if z.last_swing_idx >= cutoff]


def _filter_overlapping_zones(
    zones: List[AOIZoneCandidate], context: AOIContext
) -> List[AOIZoneCandidate]:
    if not zones:
        return []
    tol = pips_to_price(context.settings.overlap_tolerance_pips, context.pip_size)
    zones = sorted(zones, key=lambda z: z.score, reverse=True)

    selected: List[AOIZoneCandidate] = []
    for z in zones:
        overlap = any(
            not (z.upper_bound < ex.lower_bound - tol or z.lower_bound > ex.upper_bound + tol)
            for ex in selected
        )
        if not overlap:
            selected.append(z)
    return sorted(selected, key=lambda z: z.lower_bound)


def _is_zone_within_extended_bounds(
    lower: float, upper: float, context: AOIContext
) -> bool:
    return (
        (context.base_low - context.tolerance_price) <= lower
        and upper <= (context.base_high + context.tolerance_price)
    )
