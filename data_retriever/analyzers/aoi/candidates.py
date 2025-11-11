"""Candidate zone discovery for AOI analysis."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .config import AOI_MIN_TOUCHES, AOI_MIN_SWING_GAP_BARS
from .models import AOIContext, AOIZoneCandidate


IndexPrice = Tuple[int, float]


def find_zone_candidates(swings: List, last_bar_idx: int, context: AOIContext) -> List[AOIZoneCandidate]:
    """Identify AOI candidates from swing clustering with spacing and base scoring."""
    pairs: List[IndexPrice] = [(int(s[0]), float(s[1])) for s in swings]
    price_sorted: List[IndexPrice] = sorted(pairs, key=lambda x: x[1])

    candidates: Dict[Tuple[int, int], AOIZoneCandidate] = {}
    total = len(price_sorted)

    for i in range(total):
        lower_idx, lower_price = price_sorted[i]

        for j in range(i + AOI_MIN_TOUCHES - 1, total):
            upper_idx, upper_price = price_sorted[j]
            height = upper_price - lower_price

            if not is_zone_within_extended_bounds(lower_price, upper_price, context):
                break

            if height < context.min_height_price or height > context.max_height_price:
                continue

            mid_indices = [idx for (idx, price) in pairs if lower_price <= price <= upper_price]
            if len(mid_indices) < AOI_MIN_TOUCHES:
                continue
            if not has_sufficient_spacing(mid_indices):
                continue

            last_idx = max(mid_indices)
            base_score = calculate_base_zone_score(
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


def has_sufficient_spacing(indices: List[int]) -> bool:
    """Ensure swing touches are spaced out in time."""
    return all(indices[i] - indices[i - 1] >= AOI_MIN_SWING_GAP_BARS for i in range(1, len(indices)))


def calculate_base_zone_score(
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
    extremity_factor = 1 + (distance_from_mid / range_half) * 0.2  # up to +20%

    return density * recency_factor * extremity_factor


def is_zone_within_extended_bounds(lower: float, upper: float, context: AOIContext) -> bool:
    """Check if potential AOI lies within (or slightly beyond) 4H range via tolerance."""
    return (
        (context.base_low - context.tolerance_price) <= lower
        and upper <= (context.base_high + context.tolerance_price)
    )


__all__ = [
    "find_zone_candidates",
    "has_sufficient_spacing",
    "calculate_base_zone_score",
    "is_zone_within_extended_bounds",
]
