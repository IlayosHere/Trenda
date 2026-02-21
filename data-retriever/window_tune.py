#!/usr/bin/env python3
"""
Trading-window tuner.

For each seed configuration, tries every combination of:
  - symbol / symbol-group / "all symbols" filter
  - hour window (single hour, 2-hr block, 3-hr block, named session)

Degradation ladder: if full seed + window drops below 100 trades/yr,
progressively drop feature gates (least important first) until volume
is recovered, or fall back to window-only.

Seeds (from deep_tune best results):
  1. SL_AOI_FAR   RR=2.0  — aoi_height>=p75 & bearish_aoi_midpoint>=p50 & htf_range_size_high<=p90
  2. SL_SIGNAL_CANDLE RR=2.0 — bearish_htf_mid>=p75 & distance_obstacle<=p75 & hour>=5 & trend_age<=p95
  3. SL_ATR_1_0   RR=2.0  — break_close_location<=p75 & hour==8

Output: analysis/window_tune_results.csv (sorted by win_pct desc)

Usage:
    cd data-retriever
    python window_tune.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import core.env  # noqa: F401
import numpy as np
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MIN_TRADES_PER_YEAR: int = 100

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "window_tune_results.csv"

# ---------------------------------------------------------------------------
# Symbol groups
# ---------------------------------------------------------------------------
SYMBOL_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":    ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":   ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "aud_bloc":     ["AUDCAD", "AUDCHF", "AUDJPY", "AUDUSD", "EURAUD", "GBPAUD"],
    "nzd_bloc":     ["NZDCAD", "NZDCHF", "NZDJPY", "NZDSGD", "NZDUSD", "EURNZD", "GBPNZD"],
    "gbp_pairs":    ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "EURGBP"],
    "eur_pairs":    ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "chf_pairs":    ["AUDCHF", "EURCHF", "GBPCHF", "NZDCHF", "USDCHF", "CHFJPY"],
    "high_vol":     ["GBPJPY", "EURJPY", "GBPAUD", "GBPNZD", "EURAUD", "EURNZD"],
}

# ---------------------------------------------------------------------------
# Seed configurations — feature gates ordered by priority (drop from end)
# ---------------------------------------------------------------------------
# Each gate: (label, fn).  Highest-priority gates listed first.
SEEDS: list[dict] = [
    {
        "sl_model": "SL_AOI_FAR",
        "rr_multiple": 2.0,
        "label": "AOI_FAR",
        "feature_gates": [
            ("bearish_aoi_midpoint>=0.545",
             lambda d: (d["direction"] == "bearish") & (d["aoi_midpoint_range_position_high"] >= 0.545)),
            ("aoi_height>=1.512",
             lambda d: d["aoi_height_atr"] >= 1.512),
            ("htf_range_size_high<=60.5",
             lambda d: d["htf_range_size_high_atr"] <= 60.5),
        ],
    },
    {
        "sl_model": "SL_SIGNAL_CANDLE",
        "rr_multiple": 2.0,
        "label": "SIG_CANDLE",
        "feature_gates": [
            ("bearish_htf_mid>=0.829",
             lambda d: (d["direction"] == "bearish") & (d["htf_range_position_mid"] >= 0.829)),
            ("distance_obstacle<=1.060",
             lambda d: d["distance_to_next_htf_obstacle_atr"] <= 1.060),
            ("trend_age_impulses<=8",
             lambda d: d["trend_age_impulses"] <= 8.0),
        ],
    },
    {
        "sl_model": "SL_ATR_1_0",
        "rr_multiple": 2.0,
        "label": "ATR1_H8",
        "feature_gates": [
            ("break_close_location<=0.921",
             lambda d: d["break_close_location"] <= 0.921),
        ],
    },
]

# ---------------------------------------------------------------------------
# Window definitions
# ---------------------------------------------------------------------------

def _build_windows() -> list[tuple[str, Callable]]:
    """Returns list of (label, fn) for every window variant."""
    windows: list[tuple[str, Callable]] = []

    # Single hours
    for h in range(24):
        windows.append((f"h{h:02d}", lambda d, hh=h: d["hour_of_day_utc"] == hh))

    # 2-hour consecutive blocks
    for h in range(24):
        h2 = (h + 1) % 24
        windows.append((
            f"h{h:02d}-{h2:02d}",
            lambda d, a=h, b=h2: (
                d["hour_of_day_utc"].isin([a, b])
                if b > a
                else d["hour_of_day_utc"].isin([a, b])
            ),
        ))

    # 3-hour consecutive blocks
    for h in range(24):
        hrs = [(h + i) % 24 for i in range(3)]
        windows.append((
            f"h{h:02d}-{hrs[-1]:02d}(3h)",
            lambda d, hh=hrs: d["hour_of_day_utc"].isin(hh),
        ))

    # 4-hour blocks
    for h in range(0, 24, 2):
        hrs = list(range(h, h + 4))
        label = f"h{h:02d}-{h+3:02d}(4h)"
        windows.append((label, lambda d, hh=hrs: d["hour_of_day_utc"].isin(hh)))

    # Named sessions
    sessions = [
        ("asia",      list(range(0, 6))),
        ("london",    list(range(6, 12))),
        ("ny",        list(range(12, 18))),
        ("london_ny", list(range(6, 18))),
        ("asia_ld",   list(range(0, 12))),
        ("ny_close",  list(range(18, 22))),
        ("off_hours", list(range(0, 6)) + list(range(20, 24))),
    ]
    for name, hrs in sessions:
        windows.append((name, lambda d, hh=hrs: d["hour_of_day_utc"].isin(hh)))

    return windows


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"].isin({s["rr_multiple"] for s in SEEDS})].copy()
    logger.info("Loaded %d rows | %d unique signals", len(df), df["entry_signal_id"].nunique())
    return df


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _max_losing_streak(exits: list[str]) -> int:
    streak = max_streak = 0
    for e in exits:
        if e == "SL":
            streak += 1
            max_streak = max(max_streak, streak)
        elif e == "TP":
            streak = 0
    return max_streak


def compute_metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
    if len(df) < 5 or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    if tpy < MIN_TRADES_PER_YEAR:
        return None
    df_s = df.sort_values("signal_time")
    gross_profit = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gross_loss = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    return {
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "sl_pct": round(float((df_s["exit_reason"] == "SL").mean()), 4),
        "timeout_pct": round(float((df_s["exit_reason"] == "TIMEOUT").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Core evaluator — degradation ladder
# ---------------------------------------------------------------------------

def _apply_mask(df: pd.DataFrame, fns: list[Callable]) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for fn in fns:
        mask &= fn(df)
    return mask


def eval_with_degradation(
    subset: pd.DataFrame,
    feature_gate_fns: list[Callable],
    feature_gate_labels: list[str],
    window_fn: Callable,
    window_label: str,
    span_years: float,
    sl_model: str,
    rr_multiple: float,
    sym_label: str,
    seed_label: str,
) -> list[dict]:
    """Try full combo, then degrade by dropping low-priority feature gates."""
    rows: list[dict] = []

    tiers: list[tuple[str, list[Callable], list[str]]] = []

    # Build degradation tiers: full → drop last → drop last 2 → ... → window only
    for n_keep in range(len(feature_gate_fns), -1, -1):
        kept_fns = feature_gate_fns[:n_keep]
        kept_labels = feature_gate_labels[:n_keep]
        label_parts = kept_labels + ([f"sym:{sym_label}"] if sym_label != "ALL" else []) + [f"win:{window_label}"]
        gate_str = " & ".join(label_parts) if label_parts else f"win:{window_label}"
        tiers.append((gate_str, kept_fns))

    for gate_str, kept_fns in tiers:
        try:
            all_fns = kept_fns + [window_fn]
            mask = _apply_mask(subset, all_fns)
            m = compute_metrics(subset[mask], span_years)
            if m:
                rows.append({
                    "seed": seed_label,
                    "sl_model": sl_model,
                    "rr_multiple": rr_multiple,
                    "sym_filter": sym_label,
                    "window": window_label,
                    "n_feature_gates": len(kept_fns),
                    "gates": gate_str,
                    **m,
                })
                break  # found a passing tier, stop degrading
        except Exception:  # noqa: BLE001
            pass

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    windows = _build_windows()
    logger.info("Built %d window candidates", len(windows))

    # Build symbol filter variants: individual + groups + ALL
    all_symbols: list[str] = sorted(df["symbol"].dropna().unique().tolist())
    sym_variants: list[tuple[str, Optional[list[str]]]] = [("ALL", None)]
    for sym in all_symbols:
        sym_variants.append((sym, [sym]))
    for grp_name, grp_syms in SYMBOL_GROUPS.items():
        active = [s for s in grp_syms if s in all_symbols]
        if active:
            sym_variants.append((grp_name, active))

    logger.info("Symbol variants: %d (individual: %d, groups: %d, ALL: 1)",
                len(sym_variants), len(all_symbols), len(SYMBOL_GROUPS))

    all_rows: list[dict] = []

    for seed in SEEDS:
        sl_model = seed["sl_model"]
        rr = seed["rr_multiple"]
        seed_label = seed["label"]
        feature_fns = [fn for _, fn in seed["feature_gates"]]
        feature_labels = [lbl for lbl, _ in seed["feature_gates"]]

        base_subset = df[(df["sl_model"] == sl_model) & (df["rr_multiple"] == rr)].copy()
        if base_subset.empty:
            continue

        logger.info("=== Seed: %s (%d rows) ===", seed_label, len(base_subset))

        for sym_label, sym_list in sym_variants:
            # Apply symbol filter to subset
            if sym_list is None:
                sym_subset = base_subset
            else:
                sym_subset = base_subset[base_subset["symbol"].isin(sym_list)]
            if sym_subset.empty:
                continue

            for win_label, win_fn in windows:
                rows = eval_with_degradation(
                    sym_subset,
                    feature_fns,
                    feature_labels,
                    win_fn,
                    win_label,
                    span_years,
                    sl_model,
                    rr,
                    sym_label,
                    seed_label,
                )
                all_rows.extend(rows)

        logger.info("  Seed %s done. Rows so far: %d", seed_label, len(all_rows))

    if not all_rows:
        logger.error("No results produced.")
        return

    result = (
        pd.DataFrame(all_rows)
        .drop_duplicates(subset=["sl_model", "rr_multiple", "gates"])
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )

    result.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(result), OUT_PATH)

    cols = ["seed", "sl_model", "rr_multiple", "sym_filter", "window", "n_feature_gates",
            "gates", "n_trades", "trades_per_year", "win_pct",
            "expectancy_r", "max_losing_streak", "profit_factor"]
    avail = [c for c in cols if c in result.columns]

    logger.info("=== TOP 30 BY WIN_PCT ===")
    logger.info("\n%s", result[avail].head(30).to_string(index=False))

    logger.info("=== TOP 20 BY EXPECTANCY_R ===")
    logger.info("\n%s",
                result[avail].sort_values("expectancy_r", ascending=False)
                .head(20).to_string(index=False))

    # Summary: best window per seed
    logger.info("=== BEST CONFIG PER SEED (win_pct) ===")
    best_per_seed = result.groupby("seed").first().reset_index()
    logger.info("\n%s", best_per_seed[avail].to_string(index=False))

    # Symbol group leaders
    logger.info("=== BEST PER SYMBOL GROUP (win_pct, groups only) ===")
    groups_only = result[result["sym_filter"].isin(list(SYMBOL_GROUPS.keys()))]
    if not groups_only.empty:
        logger.info("\n%s", groups_only[avail].head(20).to_string(index=False))

    # Window-only results (n_feature_gates == 0) across all seeds
    window_only = result[result["n_feature_gates"] == 0]
    if not window_only.empty:
        logger.info("=== WINDOW-ONLY BEST (no feature gates) ===")
        logger.info("\n%s", window_only[avail].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
