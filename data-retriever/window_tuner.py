#!/usr/bin/env python3
"""
window_tuner.py

Surgical tuning of existing htf_zone_breakdown windows.
For each bucket (group × direction × zone), takes the existing window
and tries:
  1. Per-hour win% heatmap within the window (find weak hours)
  2. Exclude 1-2 weakest hours from the existing window
  3. Shift window ±1–2h
  4. Expand window ±1–3h
  5. Shrink window by 1–2h from each end

Then assembles an optimized portfolio and compares to baseline.
Requires minimum trade count per bucket to avoid overfitting.

Usage:
    cd data-retriever
    python window_tuner.py
"""
from __future__ import annotations

import ast
from itertools import combinations
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
MIN_TRADES_BUCKET: int = 20  # higher bar to avoid overfitting

BASE_DIR = Path(__file__).parent
ANALYSIS_DIR = BASE_DIR / "analysis"
SIGNALS_CSV = ANALYSIS_DIR / "signals.csv"
EXIT_SIM_CSV = ANALYSIS_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = ANALYSIS_DIR / "htf_zone_breakdown.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"] == RR].copy()
    df["htf_zone"] = "mid"
    df.loc[df["htf_range_position_mid"] >= PREMIUM_THRESHOLD, "htf_zone"] = "premium"
    df.loc[df["htf_range_position_mid"] <= DISCOUNT_THRESHOLD, "htf_zone"] = "discount"
    sym_to_grp = {}
    for grp, syms in EXCLUSIVE_GROUPS.items():
        for s in syms:
            sym_to_grp[s] = grp
    df["group"] = df["symbol"].map(sym_to_grp)
    df = df[df["group"].notna()].copy()
    return df


def apply_gates(df: pd.DataFrame) -> pd.DataFrame:
    bear = df["direction"] == "bearish"
    bull = df["direction"] == "bullish"
    mask = (
        (bear & (df["aoi_touch_count_since_creation"] <= 3)) |
        (bull & (df["session_directional_bias"] >= 0.0))
    )
    return df[mask].copy()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _mls(exits: list[str]) -> int:
    streak = mx = 0
    for e in exits:
        if e == "SL":
            streak += 1
            mx = max(mx, streak)
        elif e == "TP":
            streak = 0
    return mx


def metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
    if len(df) < MIN_TRADES_BUCKET or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n":   len(df_s),
        "tpy": round(tpy, 1),
        "win": round(float((df_s["exit_reason"] == "TP").mean()) * 100, 2),
        "exp": round(exp_r, 4),
        "mls": _mls(df_s["exit_reason"].tolist()),
        "pf":  round(gp / max(gl, 1e-9), 3),
    }


# ---------------------------------------------------------------------------
# Window manipulation helpers
# ---------------------------------------------------------------------------
def shift_window(hours: set[int], shift: int) -> set[int]:
    return {(h + shift) % 24 for h in hours}


def expand_window(hours: set[int], expand_left: int, expand_right: int) -> set[int]:
    sorted_h = sorted(hours)
    start = sorted_h[0]
    # find contiguous start (handle wrapping)
    new = set(hours)
    min_h = min(hours)
    max_h = max(hours)
    # Simple: find earliest and latest, expand from there
    # For wrapping windows, find the gap
    all_24 = set(range(24))
    gap = sorted(all_24 - hours)
    if not gap:
        return hours  # already 24h
    # Find contiguous gap to determine start/end of window
    gap_start = gap[0]
    # The window ends just before gap_start and starts just after gap ends
    window_end = (gap_start - 1) % 24
    window_start = (gap[-1] + 1) % 24
    # Expand
    for i in range(1, expand_left + 1):
        new.add((window_start - i) % 24)
    for i in range(1, expand_right + 1):
        new.add((window_end + i) % 24)
    return new


def shrink_window(hours: set[int], shrink_left: int, shrink_right: int) -> set[int]:
    if len(hours) <= shrink_left + shrink_right + 2:
        return hours  # can't shrink that much
    all_24 = set(range(24))
    gap = sorted(all_24 - hours)
    if not gap:
        return hours
    window_start = (gap[-1] + 1) % 24
    window_end = (gap[0] - 1) % 24
    new = set(hours)
    for i in range(shrink_left):
        new.discard((window_start + i) % 24)
    for i in range(shrink_right):
        new.discard((window_end - i) % 24)
    return new


def window_label(hours: set[int]) -> str:
    if len(hours) >= 24:
        return "ALL_24h"
    sorted_h = sorted(hours)
    return f"h{sorted_h[0]:02d}+{len(hours)}h"


# ---------------------------------------------------------------------------
# Per-bucket tuning
# ---------------------------------------------------------------------------
def tune_bucket(
    bucket_df: pd.DataFrame,
    orig_hours: set[int],
    orig_sl_model: str,
    span_years: float,
) -> list[dict]:
    """Try all variants for one bucket."""
    sl_df = bucket_df[bucket_df["sl_model"] == orig_sl_model]
    variants: list[tuple[str, set[int]]] = []

    # 0. Original
    variants.append(("ORIGINAL", orig_hours))

    # 1. Exclude 1 hour (each hour in window)
    for h in sorted(orig_hours):
        reduced = orig_hours - {h}
        if len(reduced) >= 3:
            variants.append((f"excl_{h:02d}", reduced))

    # 2. Exclude 2 consecutive hours
    for h in sorted(orig_hours):
        h2 = (h + 1) % 24
        if h2 in orig_hours:
            reduced = orig_hours - {h, h2}
            if len(reduced) >= 3:
                variants.append((f"excl_{h:02d}+{h2:02d}", reduced))

    # 3. Shift ±1, ±2
    for s in [-2, -1, 1, 2]:
        variants.append((f"shift{s:+d}", shift_window(orig_hours, s)))

    # 4. Expand ±1, ±2, ±3
    for el in range(4):
        for er in range(4):
            if el == 0 and er == 0:
                continue
            expanded = expand_window(orig_hours, el, er)
            if expanded != orig_hours:
                variants.append((f"exp_L{el}R{er}", expanded))

    # 5. Shrink 1 from left, right, or both
    for sl_amt in range(3):
        for sr_amt in range(3):
            if sl_amt == 0 and sr_amt == 0:
                continue
            shrunk = shrink_window(orig_hours, sl_amt, sr_amt)
            if shrunk != orig_hours and len(shrunk) >= 3:
                variants.append((f"shrk_L{sl_amt}R{sr_amt}", shrunk))

    # Deduplicate by frozenset
    seen: set[frozenset[int]] = set()
    results = []
    for label, hours in variants:
        key = frozenset(hours)
        if key in seen:
            continue
        seen.add(key)
        filtered = sl_df[sl_df["hour_of_day_utc"].isin(hours)]
        m = metrics(filtered, span_years)
        if m is None:
            continue
        results.append({
            "variant": label,
            "hours": sorted(hours),
            "window": window_label(hours),
            "size": len(hours),
            **m,
        })

    return sorted(results, key=lambda r: r["win"], reverse=True)


# ---------------------------------------------------------------------------
# Build portfolio
# ---------------------------------------------------------------------------
def build_portfolio(gated_df: pd.DataFrame, configs: list[dict]) -> pd.DataFrame:
    parts = []
    for cfg in configs:
        hours = set(cfg["hours"]) if isinstance(cfg["hours"], list) else cfg["hours"]
        sub = gated_df[
            (gated_df["group"] == cfg["group"]) &
            (gated_df["direction"] == cfg["direction"]) &
            (gated_df["htf_zone"] == cfg["zone"]) &
            (gated_df["sl_model"] == cfg["sl_model"]) &
            (gated_df["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", span_years, len(df))

    gated = apply_gates(df)
    logger.info("After gates: %d rows", len(gated))

    # Load original breakdown
    breakdown = pd.read_csv(BREAKDOWN_CSV)
    best_orig = (
        breakdown
        .sort_values("win_pct", ascending=False)
        .drop_duplicates(subset=["group", "direction", "zone"])
    )

    original_configs = []
    tuned_configs = []

    logger.info("\n" + "=" * 120)
    logger.info("PER-BUCKET SURGICAL TUNING")
    logger.info("=" * 120)

    for _, row in best_orig.iterrows():
        grp = row["group"]
        direction = row["direction"]
        zone = row["zone"]
        sl_model = row["sl_model"]
        orig_hours = set(ast.literal_eval(str(row["window_hours"])))
        key = f"{grp}|{direction}|{zone}"

        bucket_df = gated[
            (gated["group"] == grp) &
            (gated["direction"] == direction) &
            (gated["htf_zone"] == zone)
        ]

        orig_cfg = {
            "group": grp, "direction": direction, "zone": zone,
            "sl_model": sl_model, "hours": sorted(orig_hours),
        }
        original_configs.append(orig_cfg)

        if len(bucket_df) < 10:
            tuned_configs.append(orig_cfg)
            continue

        results = tune_bucket(bucket_df, orig_hours, sl_model, span_years)
        if not results:
            tuned_configs.append(orig_cfg)
            continue

        # Per-hour heatmap within original window
        sl_df = bucket_df[bucket_df["sl_model"] == sl_model]
        hour_stats = []
        for h in sorted(orig_hours):
            hdf = sl_df[sl_df["hour_of_day_utc"] == h]
            if len(hdf) >= 3:
                w = round(float((hdf["exit_reason"] == "TP").mean()) * 100, 1)
                hour_stats.append({"h": h, "n": len(hdf), "win%": w})

        orig_result = [r for r in results if r["variant"] == "ORIGINAL"]
        orig_win = orig_result[0]["win"] if orig_result else 0
        best = results[0]
        improvement = best["win"] - orig_win

        logger.info(
            "\n--- %s  (SL=%s, orig=%s, pool=%d) ---",
            key, sl_model, window_label(orig_hours), len(bucket_df),
        )
        if hour_stats:
            hsdf = pd.DataFrame(hour_stats)
            logger.info("  Per-hour: %s", hsdf.to_dict("records"))

        if improvement > 0.5:
            logger.info(
                "  ★ IMPROVED: %s → %s  win %.2f%% → %.2f%% (+%.2f%%)  n=%d→%d",
                "ORIGINAL", best["variant"], orig_win, best["win"], improvement,
                orig_result[0]["n"] if orig_result else 0, best["n"],
            )
            tuned_configs.append({
                "group": grp, "direction": direction, "zone": zone,
                "sl_model": sl_model, "hours": best["hours"],
                "variant": best["variant"],
            })
        else:
            logger.info("  → No improvement (best variant matches original)")
            tuned_configs.append(orig_cfg)

        # Show top 5 variants
        rdf = pd.DataFrame(results[:8])
        disp = ["variant", "window", "size", "n", "tpy", "win", "exp", "mls", "pf"]
        avail = [c for c in disp if c in rdf.columns]
        logger.info("\n%s", rdf[avail].to_string(index=False))

    # ------------------------------------------------------------------
    # Build portfolios
    # ------------------------------------------------------------------
    old_pf = build_portfolio(gated, original_configs)
    new_pf = build_portfolio(gated, tuned_configs)

    old_m = metrics(old_pf, span_years)
    new_m = metrics(new_pf, span_years)

    logger.info("\n" + "=" * 120)
    logger.info("PORTFOLIO COMPARISON")
    logger.info("=" * 120)
    for label, m in [("ORIGINAL windows", old_m), ("TUNED windows", new_m)]:
        if m:
            flag = " ✓" if m["tpy"] >= 100 else ""
            logger.info(
                "  %-20s  n=%4d  tpy=%6.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f%s",
                label, m["n"], m["tpy"], m["win"], m["exp"], m["mls"], m["pf"], flag,
            )

    # ------------------------------------------------------------------
    # Also try global hour exclusion on the tuned portfolio
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 120)
    logger.info("TUNED PORTFOLIO + GLOBAL HOUR EXCLUSIONS (tpy >= 100)")
    logger.info("=" * 120)

    rows = []
    for excl_size in [2, 3, 4, 5, 6]:
        for start in range(24):
            excl = set((start + i) % 24 for i in range(excl_size))
            f = new_pf[~new_pf["hour_of_day_utc"].isin(excl)]
            m = metrics(f, span_years)
            if m and m["tpy"] >= 100:
                rows.append({"excl": f"excl_h{start:02d}+{excl_size}h", **m})
    if rows:
        edf = pd.DataFrame(rows).sort_values("win", ascending=False)
        disp = ["excl", "n", "tpy", "win", "exp", "mls", "pf"]
        logger.info("\n  Top 15:")
        logger.info("\n%s", edf[disp].head(15).to_string(index=False))

    # ------------------------------------------------------------------
    # Per-direction breakdown for tuned portfolio
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 120)
    logger.info("TUNED PORTFOLIO — PER-DIRECTION")
    logger.info("=" * 120)
    for d in ["bearish", "bullish"]:
        ddf = new_pf[new_pf["direction"] == d]
        m = metrics(ddf, span_years)
        if m:
            logger.info("  %-10s  n=%4d  tpy=%6.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f",
                        d, m["n"], m["tpy"], m["win"], m["exp"], m["mls"], m["pf"])

    # Save tuned configs
    out = ANALYSIS_DIR / "tuned_window_configs.csv"
    pd.DataFrame(tuned_configs).to_csv(out, index=False)
    logger.info("\nSaved → %s", out)

    # Show what changed
    logger.info("\n" + "=" * 120)
    logger.info("CHANGES FROM ORIGINAL")
    logger.info("=" * 120)
    for orig, tuned in zip(original_configs, tuned_configs):
        key = f"{orig['group']}|{orig['direction']}|{orig['zone']}"
        if set(orig["hours"]) != set(tuned["hours"]):
            logger.info(
                "  CHANGED: %-35s  %s → %s  (%s)",
                key, window_label(set(orig["hours"])), window_label(set(tuned["hours"])),
                tuned.get("variant", "?"),
            )


if __name__ == "__main__":
    main()
