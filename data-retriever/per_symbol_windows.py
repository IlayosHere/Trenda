#!/usr/bin/env python3
"""
Per-symbol trading window optimizer.

For each symbol independently, find the best set of trading hours that
maximizes win_pct / expectancy_r with minimum volume.

Then builds a portfolio: each symbol trades only in its own best window.
Portfolio is evaluated as the union of all symbol-filtered rows.

Approach per symbol:
  1. Compute per-hour expectancy_r and win_pct.
  2. Rank hours best→worst by expectancy_r.
  3. Try "keep best N hours" for N = 2..20 (contiguous and non-contiguous).
  4. Also try named sessions as positive windows.
  5. Record each symbol's Pareto-optimal window options.
  6. Build portfolios: top-5/10/15/20/all symbols by individual window quality.
  7. Evaluate each portfolio → metrics across the combined trade universe.

Seeds:
  - ATR1: SL_ATR_1_0 / RR=2.0 / break_close_location<=0.921  (best from analysis)
  - SIG_CANDLE: SL_SIGNAL_CANDLE / RR=2.0 / bearish_htf_mid>=0.829 & distance_obstacle<=1.060

Output: analysis/per_symbol_window_results.csv

Usage:
    cd data-retriever
    python per_symbol_windows.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import numpy as np
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MIN_TRADES_PER_YEAR_PORTFOLIO: int = 100
MIN_TRADES_PER_YEAR_SYMBOL: int = 15   # per-symbol floor for window discovery
MIN_TRADES_SYMBOL_ABS: int = 10        # absolute minimum trades for per-symbol stats

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "per_symbol_window_results.csv"
PORTFOLIO_OUT = BASE_DIR / "portfolio_window_results.csv"

NAMED_WINDOWS: dict[str, list[int]] = {
    "asia":         list(range(0, 6)),
    "london":       list(range(6, 12)),
    "ny":           list(range(12, 18)),
    "late_ny":      list(range(15, 22)),
    "london_ny":    list(range(6, 18)),
    "ld_open":      [6, 7, 8, 9],
    "ny_open":      [12, 13, 14, 15],
    "ny_open_ext":  [12, 13, 14, 15, 16],
    "ld_ny_core":   [7, 8, 9, 12, 13, 14, 15],
    "asia_ld":      list(range(0, 12)),
    "off_hours":    list(range(18, 24)) + list(range(0, 6)),
    "london_close": [10, 11, 12, 13],
    "pre_ld":       [4, 5, 6, 7],
    "ld_midday":    [8, 9, 10, 11],
}

SEEDS: list[dict] = [
    {
        "sl_model": "SL_ATR_1_0",
        "rr_multiple": 2.0,
        "label": "ATR1",
        "filter_fn": lambda d: d["break_close_location"] <= 0.921,
    },
    {
        "sl_model": "SL_SIGNAL_CANDLE",
        "rr_multiple": 2.0,
        "label": "SIG_CANDLE",
        "filter_fn": lambda d: (
            (d["direction"] == "bearish")
            & (d["htf_range_position_mid"] >= 0.829)
            & (d["distance_to_next_htf_obstacle_atr"] <= 1.060)
        ),
    },
]

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"].isin({s["rr_multiple"] for s in SEEDS})].copy()
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


def compute_metrics(
    df: pd.DataFrame,
    span_years: float,
    min_tpy: float = MIN_TRADES_PER_YEAR_SYMBOL,
) -> Optional[dict]:
    if len(df) < MIN_TRADES_SYMBOL_ABS or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    if tpy < min_tpy:
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
# Per-symbol window discovery
# ---------------------------------------------------------------------------

def find_symbol_windows(
    sym_df: pd.DataFrame,
    span_years: float,
    symbol: str,
) -> list[dict]:
    """Find all viable window options for a single symbol. Returns rows sorted by win_pct."""
    rows: list[dict] = []

    # Per-hour stats — rank hours best→worst by expectancy_r
    per_hour = (
        sym_df.groupby("hour_of_day_utc")["return_r"]
        .mean()
        .sort_values(ascending=False)
    )
    hours_best_to_worst: list[int] = per_hour.index.tolist()
    hours_worst_to_best: list[int] = list(reversed(hours_best_to_worst))

    def _record(hours_kept: list[int], win_label: str) -> None:
        mask = sym_df["hour_of_day_utc"].isin(hours_kept)
        filtered = sym_df[mask]
        m = compute_metrics(filtered, span_years)
        if m:
            rows.append({
                "symbol": symbol,
                "window_name": win_label,
                "hours_kept": sorted(hours_kept),
                "n_hours": len(hours_kept),
                **m,
            })

    # Strategy A: keep best N hours (non-contiguous, sorted by quality)
    for n_keep in range(2, 21):
        kept = hours_best_to_worst[:n_keep]
        _record(kept, f"best_{n_keep}h")

    # Strategy B: exclude worst N hours (keeps contiguous-ish quality block)
    all_hours = set(range(24))
    for n_excl in range(1, 17):
        excluded = set(hours_worst_to_best[:n_excl])
        kept = sorted(all_hours - excluded)
        _record(kept, f"excl_{n_excl}worst")

    # Strategy C: named session windows
    for win_name, hours in NAMED_WINDOWS.items():
        _record(hours, win_name)

    # Strategy D: all contiguous N-hour windows starting at each hour
    for start in range(24):
        for length in range(2, 13):
            hours = [(start + i) % 24 for i in range(length)]
            label = f"h{start:02d}+{length}h"
            _record(hours, label)

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Portfolio builder
# ---------------------------------------------------------------------------

def build_portfolio(
    sym_best_windows: dict[str, list[int]],
    base_df: pd.DataFrame,
    span_years: float,
    label: str,
) -> Optional[dict]:
    """Combine symbol-specific window filters into a single trade universe."""
    parts: list[pd.DataFrame] = []
    for sym, hours in sym_best_windows.items():
        sym_mask = (base_df["symbol"] == sym) & base_df["hour_of_day_utc"].isin(hours)
        parts.append(base_df[sym_mask])
    if not parts:
        return None
    combined = pd.concat(parts, ignore_index=True)
    m = compute_metrics(combined, span_years, min_tpy=MIN_TRADES_PER_YEAR_PORTFOLIO)
    if m is None:
        return None
    return {
        "portfolio": label,
        "n_symbols": len(sym_best_windows),
        "symbols": sorted(sym_best_windows.keys()),
        **m,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    all_sym_rows: list[dict] = []
    portfolio_rows: list[dict] = []

    for seed in SEEDS:
        sl_model = seed["sl_model"]
        rr = seed["rr_multiple"]
        seed_label = seed["label"]

        base_subset = df[
            (df["sl_model"] == sl_model)
            & (df["rr_multiple"] == rr)
            & seed["filter_fn"](df)
        ].copy()

        if base_subset.empty:
            continue

        symbols = sorted(base_subset["symbol"].dropna().unique())
        logger.info("[%s] %d symbols, %d rows", seed_label, len(symbols), len(base_subset))

        # --- Per-symbol window discovery ---
        sym_best: dict[str, dict] = {}   # symbol → best single window row
        sym_windows_all: dict[str, list[dict]] = {}

        for sym in symbols:
            sym_df = base_subset[base_subset["symbol"] == sym].copy()
            window_rows = find_symbol_windows(sym_df, span_years, sym)
            if not window_rows:
                continue
            sym_windows_all[sym] = window_rows
            sym_best[sym] = window_rows[0]  # best by win_pct

            # Attach seed info and record
            for r in window_rows[:10]:  # keep top-10 per symbol
                all_sym_rows.append({
                    "seed": seed_label,
                    "sl_model": sl_model,
                    "rr_multiple": rr,
                    **r,
                })

            logger.info(
                "  %s: best window=%s  win=%.4f  exp=%.4f  tpy=%.1f  streak=%d  hours=%s",
                sym, sym_best[sym]["window_name"],
                sym_best[sym]["win_pct"], sym_best[sym]["expectancy_r"],
                sym_best[sym]["trades_per_year"], sym_best[sym]["max_losing_streak"],
                sym_best[sym]["hours_kept"],
            )

        if not sym_best:
            continue

        # --- Portfolio construction ---
        # Sort symbols by their best individual window quality
        ranked_symbols = sorted(
            sym_best.keys(),
            key=lambda s: (sym_best[s]["win_pct"], sym_best[s]["expectancy_r"]),
            reverse=True,
        )

        # Build portfolios of top-N symbols
        for n_syms in [5, 10, 15, 20, len(ranked_symbols)]:
            selected = ranked_symbols[:n_syms]
            windows = {s: sym_best[s]["hours_kept"] for s in selected}
            row = build_portfolio(windows, base_subset, span_years,
                                  f"{seed_label}_top{n_syms}")
            if row:
                row["seed"] = seed_label
                row["window_strategy"] = "best_per_symbol"
                portfolio_rows.append(row)

        # Also try: all symbols use the same top-N hours (global best hours for this seed)
        # Find globally best hours across all symbols
        global_per_hour = (
            base_subset.groupby("hour_of_day_utc")["return_r"]
            .mean()
            .sort_values(ascending=False)
        )
        global_best_hours = global_per_hour.index.tolist()

        for n_keep in [4, 6, 8, 10, 12, 14, 16]:
            hours = global_best_hours[:n_keep]
            mask = base_subset["hour_of_day_utc"].isin(hours)
            m = compute_metrics(base_subset[mask], span_years,
                                min_tpy=MIN_TRADES_PER_YEAR_PORTFOLIO)
            if m:
                portfolio_rows.append({
                    "seed": seed_label,
                    "sl_model": sl_model,
                    "rr_multiple": rr,
                    "portfolio": f"{seed_label}_global_best{n_keep}h",
                    "n_symbols": len(symbols),
                    "symbols": symbols,
                    "window_strategy": f"global_best_{n_keep}h",
                    "hours_kept": sorted(hours),
                    **m,
                })

        # Portfolio with each symbol using 2nd-best or 3rd-best window (robustness check)
        for window_rank in [1, 2]:
            windows_alt: dict[str, list[int]] = {}
            for s in ranked_symbols:
                opts = sym_windows_all.get(s, [])
                if len(opts) > window_rank:
                    windows_alt[s] = opts[window_rank]["hours_kept"]
                elif opts:
                    windows_alt[s] = opts[0]["hours_kept"]
            if windows_alt:
                row = build_portfolio(windows_alt, base_subset, span_years,
                                      f"{seed_label}_all_rank{window_rank + 1}")
                if row:
                    row["seed"] = seed_label
                    row["window_strategy"] = f"per_sym_rank{window_rank + 1}"
                    portfolio_rows.append(row)

    # --- Save per-symbol results ---
    if all_sym_rows:
        sym_df_out = (
            pd.DataFrame(all_sym_rows)
            .sort_values(["seed", "symbol", "win_pct"], ascending=[True, True, False])
        )
        sym_df_out.to_csv(OUT_PATH, index=False)
        logger.info("Saved %d per-symbol window rows → %s", len(sym_df_out), OUT_PATH)

        logger.info("=== TOP 30 INDIVIDUAL SYMBOL WINDOWS (by win_pct) ===")
        cols = ["seed", "symbol", "window_name", "n_hours", "hours_kept",
                "n_trades", "trades_per_year", "win_pct",
                "expectancy_r", "max_losing_streak", "profit_factor"]
        avail = [c for c in cols if c in sym_df_out.columns]
        logger.info(
            "\n%s",
            sym_df_out.sort_values("win_pct", ascending=False)[avail].head(30).to_string(index=False)
        )

    # --- Save portfolio results ---
    if portfolio_rows:
        port_df = (
            pd.DataFrame(portfolio_rows)
            .sort_values("win_pct", ascending=False)
        )
        port_df.to_csv(PORTFOLIO_OUT, index=False)
        logger.info("Saved %d portfolio rows → %s", len(port_df), PORTFOLIO_OUT)

        logger.info("=== PORTFOLIO RESULTS ===")
        port_cols = ["seed", "portfolio", "window_strategy", "n_symbols",
                     "n_trades", "trades_per_year", "win_pct",
                     "expectancy_r", "max_losing_streak", "profit_factor"]
        pavail = [c for c in port_cols if c in port_df.columns]
        logger.info("\n%s", port_df[pavail].to_string(index=False))

        logger.info("=== PORTFOLIO TOP 10 BY EXPECTANCY ===")
        logger.info(
            "\n%s",
            port_df.sort_values("expectancy_r", ascending=False)[pavail].head(10).to_string(index=False)
        )

    # --- Per-symbol summary: best window per symbol ---
    if all_sym_rows:
        sym_summary = (
            pd.DataFrame(all_sym_rows)
            .sort_values("win_pct", ascending=False)
            .drop_duplicates(subset=["seed", "symbol"])
        )
        logger.info("=== BEST WINDOW PER SYMBOL (first occurrence = best win_pct) ===")
        summary_cols = ["seed", "symbol", "window_name", "n_hours", "hours_kept",
                        "trades_per_year", "win_pct", "expectancy_r", "max_losing_streak"]
        savail = [c for c in summary_cols if c in sym_summary.columns]
        logger.info("\n%s", sym_summary[savail].to_string(index=False))


if __name__ == "__main__":
    main()
