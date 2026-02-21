#!/usr/bin/env python3
"""
gated_portfolio_optimizer.py

Re-optimize the portfolio construction (per-group SL model + hour windows)
with the gate config pre-applied: tc<=3 bear + sbias>=0 bull.

The original htf_zone_breakdown was built without gates. Now that we gate
trades, the optimal SL model and hour windows per bucket may differ.

For each (group × direction × zone):
  - Sweep all SL models available in exit_simulations
  - Sweep contiguous hour windows (3h–12h)
  - Find best combo by win%
  - Also try: best combo by expectancy_r, by profit_factor

Then assemble the optimized portfolio and compare to current.

Usage:
    cd data-retriever
    python gated_portfolio_optimizer.py
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
MIN_TRADES_BUCKET: int = 15
MIN_TPY_PORTFOLIO: float = 100.0

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

WINDOW_SIZES = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


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
    # Map symbols to groups
    sym_to_grp = {}
    for grp, syms in EXCLUSIVE_GROUPS.items():
        for s in syms:
            sym_to_grp[s] = grp
    df["group"] = df["symbol"].map(sym_to_grp)
    df = df[df["group"].notna()].copy()
    return df


def apply_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Apply tc<=3 bear + sbias>=0 bull gates."""
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


def compute_metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
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
# Window generator
# ---------------------------------------------------------------------------
def gen_windows(size: int) -> list[tuple[str, set[int]]]:
    windows = []
    for start in range(24):
        hours = set((start + i) % 24 for i in range(size))
        label = f"h{start:02d}+{size}h"
        windows.append((label, hours))
    return windows


# ---------------------------------------------------------------------------
# Per-bucket optimizer
# ---------------------------------------------------------------------------
def optimize_bucket(
    bucket_df: pd.DataFrame,
    grp: str, direction: str, zone: str,
    span_years: float,
) -> list[dict]:
    """Sweep SL models × hour windows for one (group, direction, zone) bucket."""
    sl_models = bucket_df["sl_model"].unique()
    results = []

    for sl in sl_models:
        sl_df = bucket_df[bucket_df["sl_model"] == sl]
        if len(sl_df) < MIN_TRADES_BUCKET:
            continue

        for size in WINDOW_SIZES:
            for label, hours in gen_windows(size):
                filtered = sl_df[sl_df["hour_of_day_utc"].isin(hours)]
                m = compute_metrics(filtered, span_years)
                if m is None:
                    continue
                results.append({
                    "group": grp,
                    "direction": direction,
                    "zone": zone,
                    "sl_model": sl,
                    "window": label,
                    "hours": sorted(hours),
                    **m,
                })

    return sorted(results, key=lambda r: r["win"], reverse=True)


# ---------------------------------------------------------------------------
# Portfolio assembler
# ---------------------------------------------------------------------------
def build_old_portfolio(gated_df: pd.DataFrame) -> pd.DataFrame:
    """Build portfolio using original htf_zone_breakdown (for comparison)."""
    breakdown = pd.read_csv(BREAKDOWN_CSV)
    best = (
        breakdown
        .sort_values("win_pct", ascending=False)
        .drop_duplicates(subset=["group", "direction", "zone"])
    )
    parts: list[pd.DataFrame] = []
    for _, cfg in best.iterrows():
        grp: str = cfg["group"]
        hours: set[int] = set(ast.literal_eval(str(cfg["window_hours"])))
        sub = gated_df[
            (gated_df["group"] == grp) &
            (gated_df["direction"] == cfg["direction"]) &
            (gated_df["htf_zone"] == cfg["zone"]) &
            (gated_df["sl_model"] == cfg["sl_model"]) &
            (gated_df["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 10:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_new_portfolio(
    gated_df: pd.DataFrame,
    bucket_configs: list[dict],
) -> pd.DataFrame:
    """Build portfolio from optimized bucket configs."""
    parts: list[pd.DataFrame] = []
    for cfg in bucket_configs:
        sub = gated_df[
            (gated_df["group"] == cfg["group"]) &
            (gated_df["direction"] == cfg["direction"]) &
            (gated_df["htf_zone"] == cfg["zone"]) &
            (gated_df["sl_model"] == cfg["sl_model"]) &
            (gated_df["hour_of_day_utc"].isin(set(cfg["hours"])))
        ]
        if len(sub) >= 10:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Full dataset: %.2f years | %d rows", span_years, len(df))

    gated = apply_gates(df)
    logger.info("After gates (tc<=3 bear + sbias>=0 bull): %d rows", len(gated))

    # ------------------------------------------------------------------
    # Old portfolio baseline
    # ------------------------------------------------------------------
    old_pf = build_old_portfolio(gated)
    old_m = compute_metrics(old_pf, span_years)
    logger.info("\n=== OLD PORTFOLIO (htf_zone_breakdown configs + gates) ===")
    if old_m:
        logger.info(
            "  n=%d  tpy=%.1f  win=%.2f%%  exp=%.4f  mls=%d  pf=%.3f",
            old_m["n"], old_m["tpy"], old_m["win"], old_m["exp"], old_m["mls"], old_m["pf"],
        )

    # ------------------------------------------------------------------
    # Optimize each (group, direction, zone) bucket
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 110)
    logger.info("OPTIMIZING BUCKETS: (group × direction × zone × sl_model × window)")
    logger.info("=" * 110)

    all_bucket_results: dict[str, list[dict]] = {}
    best_per_bucket: list[dict] = []

    for grp in EXCLUSIVE_GROUPS:
        for direction in ["bearish", "bullish"]:
            for zone in ["discount", "premium"]:
                bucket_df = gated[
                    (gated["group"] == grp) &
                    (gated["direction"] == direction) &
                    (gated["htf_zone"] == zone)
                ]
                if len(bucket_df) < MIN_TRADES_BUCKET:
                    continue

                key = f"{grp}|{direction}|{zone}"
                results = optimize_bucket(bucket_df, grp, direction, zone, span_years)
                if not results:
                    continue

                all_bucket_results[key] = results
                best = results[0]  # highest win%
                best_per_bucket.append(best)

                logger.info(
                    "\n--- %s (pool=%d) ---  BEST: %s %s → win=%.2f%% n=%d tpy=%.1f mls=%d",
                    key, len(bucket_df), best["sl_model"], best["window"],
                    best["win"], best["n"], best["tpy"], best["mls"],
                )
                # Show top 5
                rdf = pd.DataFrame(results[:5])
                disp = ["sl_model", "window", "n", "tpy", "win", "exp", "mls", "pf"]
                avail = [c for c in disp if c in rdf.columns]
                logger.info("\n%s", rdf[avail].to_string(index=False))

    # ------------------------------------------------------------------
    # Build optimized portfolio (top-1 per bucket by win%)
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 110)
    logger.info("NEW OPTIMIZED PORTFOLIO (best win%% per bucket)")
    logger.info("=" * 110)

    new_pf = build_new_portfolio(gated, best_per_bucket)
    new_m = compute_metrics(new_pf, span_years)
    if new_m:
        logger.info(
            "  n=%d  tpy=%.1f  win=%.2f%%  exp=%.4f  mls=%d  pf=%.3f",
            new_m["n"], new_m["tpy"], new_m["win"], new_m["exp"], new_m["mls"], new_m["pf"],
        )

    # Show per-bucket breakdown
    logger.info("\n  Per-bucket configs:")
    bdf = pd.DataFrame(best_per_bucket)
    disp = ["group", "direction", "zone", "sl_model", "window", "n", "tpy", "win", "exp", "mls"]
    avail = [c for c in disp if c in bdf.columns]
    logger.info("\n%s", bdf[avail].to_string(index=False))

    # ------------------------------------------------------------------
    # Try blending: pick top-1 by win% but require min tpy per bucket
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 110)
    logger.info("BALANCED PORTFOLIO (best win%% with bucket tpy >= 15)")
    logger.info("=" * 110)

    balanced_configs = []
    for key, results in all_bucket_results.items():
        # Pick best with tpy >= 15
        for r in results:
            if r["tpy"] >= 15:
                balanced_configs.append(r)
                break

    bal_pf = build_new_portfolio(gated, balanced_configs)
    bal_m = compute_metrics(bal_pf, span_years)
    if bal_m:
        logger.info(
            "  n=%d  tpy=%.1f  win=%.2f%%  exp=%.4f  mls=%d  pf=%.3f",
            bal_m["n"], bal_m["tpy"], bal_m["win"], bal_m["exp"], bal_m["mls"], bal_m["pf"],
        )

    # ------------------------------------------------------------------
    # Volume-maximized: pick all configs with win > 45% (broader windows)
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 110)
    logger.info("VOLUME PORTFOLIO (best win%% with bucket tpy >= 20 and win > 45%%)")
    logger.info("=" * 110)

    vol_configs = []
    for key, results in all_bucket_results.items():
        for r in results:
            if r["tpy"] >= 20 and r["win"] >= 45:
                vol_configs.append(r)
                break
        else:
            # Fallback: just get best win% with tpy >= 20
            for r in results:
                if r["tpy"] >= 20:
                    vol_configs.append(r)
                    break

    vol_pf = build_new_portfolio(gated, vol_configs)
    vol_m = compute_metrics(vol_pf, span_years)
    if vol_m:
        logger.info(
            "  n=%d  tpy=%.1f  win=%.2f%%  exp=%.4f  mls=%d  pf=%.3f",
            vol_m["n"], vol_m["tpy"], vol_m["win"], vol_m["exp"], vol_m["mls"], vol_m["pf"],
        )
    vol_bdf = pd.DataFrame(vol_configs)
    if not vol_bdf.empty:
        logger.info("\n  Per-bucket configs:")
        logger.info("\n%s", vol_bdf[avail].to_string(index=False))

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    logger.info("\n" + "=" * 110)
    logger.info("COMPARISON")
    logger.info("=" * 110)
    for label, m in [("OLD portfolio", old_m), ("NEW optimized", new_m),
                     ("BALANCED", bal_m), ("VOLUME", vol_m)]:
        if m:
            flag = " ✓" if m["tpy"] >= MIN_TPY_PORTFOLIO else ""
            logger.info(
                "  %-20s  n=%4d  tpy=%6.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f%s",
                label, m["n"], m["tpy"], m["win"], m["exp"], m["mls"], m["pf"], flag,
            )

    # Save new configs
    out = ANALYSIS_DIR / "gated_portfolio_configs.csv"
    pd.DataFrame(best_per_bucket).to_csv(out, index=False)
    logger.info("\nSaved optimized configs → %s", out)

    out2 = ANALYSIS_DIR / "gated_portfolio_balanced.csv"
    pd.DataFrame(balanced_configs).to_csv(out2, index=False)
    logger.info("Saved balanced configs → %s", out2)

    out3 = ANALYSIS_DIR / "gated_portfolio_volume.csv"
    if vol_configs:
        pd.DataFrame(vol_configs).to_csv(out3, index=False)
        logger.info("Saved volume configs → %s", out3)


if __name__ == "__main__":
    main()
