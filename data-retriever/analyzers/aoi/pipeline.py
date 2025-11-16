from dataclasses import dataclass
from typing import Dict, List, Tuple

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
    swings: List,
    last_bar_idx: int,
    context: AOIContext,
) -> List[Dict[str, float]]:
    """Full AOI generation pipeline that supports directional extensions."""

    if not swings:
        return []

    return _run_zone_pipeline(swings, last_bar_idx, context)


def _run_zone_pipeline(
    swings: List,
    last_bar_idx: int,
    context: AOIContext,
) -> List[Dict[str, float]]:
    candidates = _find_zone_candidates(swings, last_bar_idx, context)
    merged = _merge_nearby_zones(candidates, context)
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
    swings: List,
    last_bar_idx: int,
    context: AOIContext,
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

            mid_indices = [
                idx for (idx, price) in pairs if lower_price <= price <= upper_price
            ]
            if len(mid_indices) < settings.min_touches:
                break
            if not _has_sufficient_spacing(mid_indices, settings.min_swing_gap_bars):
                break

            last_idx = max(mid_indices)
            base_score = _calculate_base_zone_score(
                height,
                len(mid_indices),
                last_idx,
                last_bar_idx
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
    height: float,
    touches: int,
    last_idx: int,
    last_bar_idx: int
    ) -> float:
    """Base AOI score before trend-direction bias."""

    density = (touches ** 1.2) / max(height, 1e-6)

    bars_since_last = last_bar_idx - last_idx
    recency_factor = 1 / (1 + (bars_since_last / 100.0))
    
    extra_touches = max(touches - 3, 0)

    if extra_touches == 0:
        freshness_factor = 1.3
    elif extra_touches == 1:
        freshness_factor = 1.1
    elif extra_touches == 2:
        freshness_factor = 1.0
    else:
        freshness_factor = 0.85

    return density * recency_factor * freshness_factor

def _has_sufficient_spacing(indices: List[int], min_gap_bars: int) -> bool:
    count = 1

    for i in range(1, len(indices)):
        if indices[i] - indices[i - 1] >= min_gap_bars:
            count += 1
            if count >= 3:
                return True
            
    return False

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


