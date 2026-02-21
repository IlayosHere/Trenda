#!/usr/bin/env python3
"""
hour_window_optimizer.py

For each validated gate config (C–G from DB validation), sweep contiguous
hour-of-day windows and find the window that maximises win% while keeping
volume reasonable.

Window sizes tested: 4h, 5h, 6h, 7h, 8h, 10h, 12h, 14h, 16h
Each window slides across 0–23.

Uses the same portfolio construction as bull_gate_explorer.py (CSV-based).

Usage:
    cd data-retriever
    python hour_window_optimizer.py
"""
from __future__ import annotations

import ast
from itertools import product
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
MIN_TRADES_ABS: int = 30

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

WINDOW_SIZES = [4, 5, 6, 7, 8, 10, 12, 14, 16]


# ---------------------------------------------------------------------------
# Data loading & portfolio
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
    return df


def build_portfolio(df: pd.DataFrame) -> pd.DataFrame:
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
        sub = df[
            (df["symbol"].isin(EXCLUSIVE_GROUPS[grp])) &
            (df["direction"] == cfg["direction"]) &
            (df["htf_zone"] == cfg["zone"]) &
            (df["sl_model"] == cfg["sl_model"]) &
            (df["hour_of_day_utc"].isin(hours))
        ].copy()
        if len(sub) >= 10:
            sub["_bucket"] = f"{grp}|{cfg['direction']}|{cfg['zone']}"
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


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
    if len(df) < MIN_TRADES_ABS or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades":          len(df_s),
        "tpy":               round(tpy, 1),
        "win_pct":           round(float((df_s["exit_reason"] == "TP").mean()) * 100, 2),
        "expectancy_r":      round(exp_r, 4),
        "max_losing_streak": _mls(df_s["exit_reason"].tolist()),
        "profit_factor":     round(gp / max(gl, 1e-9), 3),
    }


# ---------------------------------------------------------------------------
# Gate configs
# ---------------------------------------------------------------------------
def make_gate_mask(df: pd.DataFrame, config_name: str) -> pd.Series:
    """Return boolean mask for the given config applied to portfolio df."""
    bear = df["direction"] == "bearish"
    bull = df["direction"] == "bullish"
    tc = df["aoi_touch_count_since_creation"]
    sbias = df["session_directional_bias"]
    height = df["aoi_height_atr"]
    touch = df["aoi_time_since_last_touch"]
    dist = df["distance_from_last_impulse_atr"]
    opp = df["signal_candle_opposite_extreme_atr"]

    if config_name == "C":
        return (bear & (tc <= 3)) | (bull & (sbias >= 0.2))
    elif config_name == "D":
        return (bear & (tc <= 3)) | (bull & (height <= 1.12) & (sbias >= 0.2))
    elif config_name == "E":
        return (bear & (tc <= 3)) | (bull & (height <= 1.12) & (touch >= 49))
    elif config_name == "F":
        return (bear & (tc <= 3)) | (bull & (height <= 0.95) & (opp <= 0.58))
    elif config_name == "G":
        return (bear & (tc <= 3) & (dist >= 0.21)) | (bull & (height <= 1.12) & (sbias >= 0.2))
    else:
        raise ValueError(f"Unknown config: {config_name}")


CONFIG_LABELS = {
    "C": "Bear tc<=3 + Bull sbias>=0.2",
    "D": "Bear tc<=3 + Bull h<=1.12+sbias>=0.2",
    "E": "Bear tc<=3 + Bull h<=1.12+touch>=49",
    "F": "Bear tc<=3 + Bull h<=0.95+opp<=0.58",
    "G": "Bear tc<=3+dist>=0.21 + Bull h<=1.12+sbias>=0.2",
}


# ---------------------------------------------------------------------------
# Window sweep
# ---------------------------------------------------------------------------
def generate_windows(size: int) -> list[tuple[int, set[int]]]:
    """Generate all contiguous hour windows of given size wrapping at 24."""
    windows = []
    for start in range(24):
        hours = set((start + i) % 24 for i in range(size))
        label_start = start
        windows.append((label_start, hours))
    return windows


def sweep_hours_for_config(
    gated_df: pd.DataFrame,
    span_years: float,
    config_name: str,
) -> list[dict]:
    """Sweep all window sizes and starting hours."""
    results: list[dict] = []

    # Baseline (no hour filter on top of gate)
    base = compute_metrics(gated_df, span_years)
    if base:
        results.append({
            "config": config_name,
            "window": "ALL (no hour filter)",
            "start_h": -1,
            "size": 24,
            **base,
        })

    for size in WINDOW_SIZES:
        for start, hours in generate_windows(size):
            filtered = gated_df[gated_df["hour_of_day_utc"].isin(hours)]
            m = compute_metrics(filtered, span_years)
            if m is None:
                continue
            results.append({
                "config": config_name,
                "window": f"h{start:02d}+{size}h",
                "start_h": start,
                "size": size,
                **m,
            })

    return sorted(results, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Exclude-window sweep (exclude bad hours instead of include good ones)
# ---------------------------------------------------------------------------
def sweep_exclude_hours(
    gated_df: pd.DataFrame,
    span_years: float,
    config_name: str,
) -> list[dict]:
    """Try excluding contiguous blocks of 2-6 hours."""
    results: list[dict] = []
    for excl_size in [2, 3, 4, 5, 6]:
        for start in range(24):
            excl_hours = set((start + i) % 24 for i in range(excl_size))
            keep_hours = set(range(24)) - excl_hours
            filtered = gated_df[gated_df["hour_of_day_utc"].isin(keep_hours)]
            m = compute_metrics(filtered, span_years)
            if m is None:
                continue
            results.append({
                "config": config_name,
                "exclude": f"excl_h{start:02d}+{excl_size}h",
                "excl_start": start,
                "excl_size": excl_size,
                **m,
            })
    return sorted(results, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", span_years, len(df))

    portfolio = build_portfolio(df)
    if portfolio.empty:
        logger.error("Portfolio empty")
        return
    logger.info("Portfolio: %d trades", len(portfolio))

    for cfg_key, cfg_label in CONFIG_LABELS.items():
        logger.info("\n" + "=" * 100)
        logger.info("CONFIG %s: %s", cfg_key, cfg_label)
        logger.info("=" * 100)

        mask = make_gate_mask(portfolio, cfg_key)
        gated = portfolio[mask].copy()
        logger.info("Gated trades: %d", len(gated))

        # ---------- INCLUDE windows ----------
        inc_results = sweep_hours_for_config(gated, span_years, cfg_key)
        if inc_results:
            inc_df = pd.DataFrame(inc_results)
            disp = ["window", "n_trades", "tpy", "win_pct", "expectancy_r",
                    "max_losing_streak", "profit_factor"]
            avail = [c for c in disp if c in inc_df.columns]

            logger.info("\n--- TOP 15 INCLUDE windows (by win%%) ---")
            logger.info("\n%s", inc_df[avail].head(15).to_string(index=False))

            # Show best per window size (volume-balanced view)
            logger.info("\n--- BEST per window size ---")
            best_per_size = (
                inc_df[inc_df["start_h"] >= 0]
                .sort_values("win_pct", ascending=False)
                .drop_duplicates("size")
                .sort_values("size")
            )
            logger.info("\n%s", best_per_size[avail].to_string(index=False))

        # ---------- EXCLUDE windows ----------
        excl_results = sweep_exclude_hours(gated, span_years, cfg_key)
        if excl_results:
            excl_df = pd.DataFrame(excl_results)
            disp_e = ["exclude", "n_trades", "tpy", "win_pct", "expectancy_r",
                      "max_losing_streak", "profit_factor"]
            avail_e = [c for c in disp_e if c in excl_df.columns]

            logger.info("\n--- TOP 10 EXCLUDE windows (by win%%) ---")
            logger.info("\n%s", excl_df[avail_e].head(10).to_string(index=False))

    # Per-direction hour heatmap for config G (the strongest)
    logger.info("\n" + "=" * 100)
    logger.info("HOUR HEATMAP — Config G per direction")
    logger.info("=" * 100)
    mask_g = make_gate_mask(portfolio, "G")
    gated_g = portfolio[mask_g].copy()
    for direction in ["bearish", "bullish"]:
        dir_df = gated_g[gated_g["direction"] == direction]
        if len(dir_df) < 20:
            continue
        logger.info("\n--- %s (n=%d) ---", direction, len(dir_df))
        hour_stats = []
        for h in range(24):
            hdf = dir_df[dir_df["hour_of_day_utc"] == h]
            if len(hdf) < 5:
                continue
            win = round(float((hdf["exit_reason"] == "TP").mean()) * 100, 1)
            hour_stats.append({"hour": h, "n": len(hdf), "win%": win})
        if hour_stats:
            logger.info("\n%s", pd.DataFrame(hour_stats).to_string(index=False))


if __name__ == "__main__":
    main()
