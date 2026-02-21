#!/usr/bin/env python3
"""
HTF range position — direction split analysis.

Investigates whether htf_range_position_mid has different predictive
value for bearish vs bullish trades in the ATR1 top-15 portfolio.

Hypotheses:
  H1: bearish benefits from high HTF position (price at top of range → good short)
  H2: bullish benefits from low HTF position (price at bottom → good long)
  H3: one direction dominates the signal; the other is noise

Approach:
  1. Split fixed portfolio by direction → inspect distributions and metrics
  2. Sweep htf thresholds INDEPENDENTLY per direction
  3. Find direction-specific optimal thresholds
  4. Build combined portfolio: bearish filtered by best_b, bullish by best_bull
  5. Compare vs uniform threshold and prior baselines
  6. Also test: direction-only portfolios (bearish-only, bullish-only)

Reference points:
  - Baseline (no gate):                         40.71% win, 267 tpy
  - bars<=2 & dist>=0.25 (prior best depth-2):  43.79% win, 151 tpy
  - htf_range_mid>=0.4 (best htf single):       41.92% win, 153 tpy
  - htf_dir>=0.4 & bars<=3 & dist>=0.25:        44.23% win, 101.5 tpy

Output: analysis/htf_direction_split_results.csv

Usage:
    cd data-retriever
    python htf_direction_split.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TPY: int = 100
MIN_TRADES_ABS: int = 50
MIN_TPY_SYMBOL: int = 20

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "htf_direction_split_results.csv"

# ATR1 top-15 fixed portfolio
PORTFOLIO: dict[str, list[int]] = {
    "AUDUSD": list(range(10, 15)),
    "EURNZD": list(range(6,  10)),
    "GBPUSD": list(range(14, 18)),
    "EURJPY": list(range(12, 16)),
    "GBPJPY": list(range(6,  10)),
    "USDJPY": list(range(0,  6)),
    "CADJPY": list(range(6,  10)),
    "NZDJPY": list(range(12, 16)),
    "AUDJPY": list(range(6,  10)),
    "EURUSD": list(range(0,  6)),
    "GBPCAD": list(range(4,  8)),
    "CHFJPY": list(range(12, 16)),
    "USDCHF": list(range(6,  10)),
    "AUDCAD": list(range(14, 18)),
    "GBPNZD": list(range(8,  12)),
}

# Thresholds for sweep
HTF_THRESHOLDS: list[float] = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

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
    min_tpy: float = MIN_TPY,
    label: str = "",
) -> Optional[dict]:
    if len(df) < MIN_TRADES_ABS or span_years < 0.01:
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
        "label": label,
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


def compute_metrics_relaxed(
    df: pd.DataFrame,
    span_years: float,
    label: str = "",
) -> Optional[dict]:
    """Relaxed version — no tpy floor, for per-direction stats."""
    if len(df) < 30 or span_years < 0.01:
        return None
    df_s = df.sort_values("signal_time")
    tpy = len(df_s) / span_years
    gross_profit = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gross_loss = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    exp_r = float(df_s["return_r"].mean())
    return {
        "label": label,
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    return df[
        (df["sl_model"] == "SL_ATR_1_0")
        & (df["rr_multiple"] == 2.0)
        & (df["break_close_location"] <= 0.921)
    ].copy()


def build_portfolio(base_df: pd.DataFrame) -> pd.DataFrame:
    parts = [
        base_df[(base_df["symbol"] == sym) & base_df["hour_of_day_utc"].isin(hours)]
        for sym, hours in PORTFOLIO.items()
    ]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("ATR1 seed: %.2f years, %d rows", span_years, len(df))

    htf_col = "htf_range_position_mid"
    dir_col = "direction"

    if htf_col not in df.columns:
        logger.error("%s not in data", htf_col)
        return

    port_df = build_portfolio(df)
    logger.info("Fixed portfolio: %d rows", len(port_df))

    # ── 1. Direction distribution ────────────────────────────────────────────
    if dir_col in port_df.columns:
        dir_counts = port_df[dir_col].value_counts()
        dir_pct = port_df[dir_col].value_counts(normalize=True).round(4)
        logger.info("=== DIRECTION DISTRIBUTION (portfolio) ===")
        for d in dir_counts.index:
            logger.info("  %-10s  n=%d  (%.1f%%)", d, dir_counts[d], dir_pct[d] * 100)
    else:
        logger.warning("'direction' column not found — direction split skipped")
        dir_col = None

    # ── 2. HTF distribution per direction ───────────────────────────────────
    logger.info("=== HTF_RANGE_POSITION_MID DISTRIBUTION PER DIRECTION ===")
    for direction in (["bearish", "bullish"] if dir_col else ["all"]):
        sub = port_df[port_df[dir_col] == direction] if dir_col else port_df
        if len(sub) < 30:
            logger.info("  %s: too few rows (%d)", direction, len(sub))
            continue
        s = sub[htf_col].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
        logger.info(
            "  %-10s  n=%-5d  min=%.3f  p10=%.3f  p25=%.3f  "
            "p50=%.3f  p75=%.3f  p90=%.3f  max=%.3f",
            direction, len(sub),
            s["min"], s["10%"], s["25%"], s["50%"], s["75%"], s["90%"], s["max"],
        )

        # Win% without any htf gate
        m = compute_metrics_relaxed(sub, span_years, label=f"{direction}_no_gate")
        if m:
            logger.info(
                "    → no_gate: win=%.4f  exp=%.4f  tpy=%.1f",
                m["win_pct"], m["expectancy_r"], m["trades_per_year"],
            )

    # ── 3. Per-direction threshold sweep ────────────────────────────────────
    logger.info("=== PER-DIRECTION HTF THRESHOLD SWEEP ===")

    all_rows: list[dict] = []

    # For each direction, sweep htf thresholds in BOTH directions (>= and <=)
    for direction in (["bearish", "bullish"] if dir_col else ["all"]):
        dir_df = port_df[port_df[dir_col] == direction].copy() if dir_col else port_df.copy()
        logger.info("--- %s (n=%d) ---", direction, len(dir_df))

        for threshold in HTF_THRESHOLDS:
            # High-range filter (>= threshold)
            high = dir_df[dir_df[htf_col] >= threshold]
            m = compute_metrics_relaxed(high, span_years,
                                        label=f"{direction}|htf>={threshold}")
            if m:
                m["direction"] = direction
                m["gate_form"] = f"htf>={threshold}"
                m["threshold"] = threshold
                m["filter_dir"] = "high"
                all_rows.append(m)
                logger.info(
                    "  %s htf>=%s: n=%-5d  win=%.4f  exp=%.4f  tpy=%.1f",
                    direction, threshold, m["n_trades"],
                    m["win_pct"], m["expectancy_r"], m["trades_per_year"],
                )

            # Low-range filter (<= threshold)
            low = dir_df[dir_df[htf_col] <= threshold]
            m2 = compute_metrics_relaxed(low, span_years,
                                         label=f"{direction}|htf<={threshold}")
            if m2:
                m2["direction"] = direction
                m2["gate_form"] = f"htf<={threshold}"
                m2["threshold"] = threshold
                m2["filter_dir"] = "low"
                all_rows.append(m2)

    # ── 4. Direction-only portfolios (exclude one direction entirely) ─────────
    logger.info("=== DIRECTION-ONLY PORTFOLIOS ===")
    if dir_col:
        for direction in ["bearish", "bullish"]:
            dir_only = port_df[port_df[dir_col] == direction]
            m = compute_metrics(dir_only, span_years, min_tpy=MIN_TPY,
                                label=f"portfolio_{direction}_only_no_gate")
            if m:
                m["direction"] = direction
                m["gate_form"] = "direction_only"
                m["threshold"] = None
                m["filter_dir"] = "dir_only"
                all_rows.append(m)
                logger.info("  %s-only no_gate: win=%.4f  tpy=%.1f  exp=%.4f  streak=%d",
                            direction, m["win_pct"], m["trades_per_year"],
                            m["expectancy_r"], m["max_losing_streak"])
            else:
                logger.info("  %s-only: below floor (< %d tpy)", direction, MIN_TPY)

    # ── 5. Grid: direction-specific thresholds → combined portfolio ──────────
    logger.info("=== COMBINED DIRECTIONAL THRESHOLD GRID ===")

    if dir_col and "bearish" in port_df[dir_col].values and "bullish" in port_df[dir_col].values:
        bearish_df = port_df[port_df[dir_col] == "bearish"]
        bullish_df = port_df[port_df[dir_col] == "bullish"]

        # Find best individual thresholds from step 3 to narrow the grid
        # Test cross combinations: bearish(htf>=b) + bullish(htf<=bull_t OR htf>=bull_t)
        b_thresholds = [t for t in HTF_THRESHOLDS if t >= 0.35]
        bull_thresholds = [t for t in HTF_THRESHOLDS if t <= 0.65]

        for b_thresh in b_thresholds:
            b_sub = bearish_df[bearish_df[htf_col] >= b_thresh]

            for bull_thresh in bull_thresholds:
                # Case A: bullish wants LOW range (< bull_thresh)
                bull_sub_low = bullish_df[bullish_df[htf_col] <= bull_thresh]
                combined_a = pd.concat([b_sub, bull_sub_low], ignore_index=True)
                m = compute_metrics(
                    combined_a, span_years, min_tpy=MIN_TPY,
                    label=f"bear>={b_thresh} & bull<={bull_thresh}",
                )
                if m:
                    m["direction"] = "combined"
                    m["gate_form"] = f"bear_htf>={b_thresh}_bull_htf<={bull_thresh}"
                    m["threshold"] = b_thresh
                    m["filter_dir"] = "split_low"
                    all_rows.append(m)

                # Case B: bullish wants HIGH range too (>= bull_thresh)
                bull_sub_high = bullish_df[bullish_df[htf_col] >= bull_thresh]
                combined_b = pd.concat([b_sub, bull_sub_high], ignore_index=True)
                m2 = compute_metrics(
                    combined_b, span_years, min_tpy=MIN_TPY,
                    label=f"bear>={b_thresh} & bull>={bull_thresh}",
                )
                if m2:
                    m2["direction"] = "combined"
                    m2["gate_form"] = f"bear_htf>={b_thresh}_bull_htf>={bull_thresh}"
                    m2["threshold"] = b_thresh
                    m2["filter_dir"] = "split_high"
                    all_rows.append(m2)

    # ── 6. Combined directional + prior best gates ───────────────────────────
    logger.info("=== DIRECTION-SPLIT + PRIOR BEST GATE OVERLAY ===")

    if dir_col:
        bearish_df = port_df[port_df[dir_col] == "bearish"]
        bullish_df = port_df[port_df[dir_col] == "bullish"]

        # Apply known best single gate to each direction separately, then recombine
        overlay_gates: list[tuple[str, str, float]] = [
            ("bars_between_retest_and_break",     "<=", 2),
            ("bars_between_retest_and_break",     "<=", 3),
            ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
            ("break_close_location",               ">=", 0.65),
            ("max_retest_penetration_atr",         "<=", 1.25),
        ]

        for g_col, g_op, g_val in overlay_gates:
            if g_col not in port_df.columns:
                continue
            gate_label = f"{g_col}{g_op}{g_val}"

            for b_thresh in [0.40, 0.45, 0.50]:
                # bearish: htf >= b_thresh + overlay gate
                if g_op == "<=":
                    b_sub = bearish_df[
                        (bearish_df[htf_col] >= b_thresh) & (bearish_df[g_col] <= g_val)
                    ]
                else:
                    b_sub = bearish_df[
                        (bearish_df[htf_col] >= b_thresh) & (bearish_df[g_col] >= g_val)
                    ]

                # bullish: htf <= (1-b_thresh) + overlay gate (same structural gate)
                bull_thresh = 1.0 - b_thresh
                if g_op == "<=":
                    bull_sub = bullish_df[
                        (bullish_df[htf_col] <= bull_thresh) & (bullish_df[g_col] <= g_val)
                    ]
                else:
                    bull_sub = bullish_df[
                        (bullish_df[htf_col] <= bull_thresh) & (bullish_df[g_col] >= g_val)
                    ]

                combined = pd.concat([b_sub, bull_sub], ignore_index=True)
                lbl = f"dir_split_htf>={b_thresh}/<={bull_thresh} & {gate_label}"
                m = compute_metrics(combined, span_years, min_tpy=MIN_TPY, label=lbl)
                if m:
                    m["direction"] = "combined"
                    m["gate_form"] = lbl
                    m["threshold"] = b_thresh
                    m["filter_dir"] = "dir_split_gate"
                    all_rows.append(m)

    # ── 7. Save and report ───────────────────────────────────────────────────
    if not all_rows:
        logger.warning("No results generated")
        return

    results = pd.DataFrame(all_rows)

    # Separate portfolio-level results (have trades_per_year) from per-direction stats
    port_results = results[
        results["direction"].isin(["combined", "bearish", "bullish"])
        & results["label"].notna()
    ].copy()

    results.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(results), OUT_PATH)

    # Report: per-direction threshold sweep tables
    logger.info("=== BEARISH — HTF THRESHOLD SWEEP (>= and <=) ===")
    bear = results[(results["direction"] == "bearish")].sort_values(
        "win_pct", ascending=False
    )
    report_cols = ["label", "n_trades", "trades_per_year", "win_pct",
                   "expectancy_r", "max_losing_streak", "profit_factor"]
    avail = [c for c in report_cols if c in bear.columns]
    logger.info("\n%s", bear[avail].head(15).to_string(index=False))

    logger.info("=== BULLISH — HTF THRESHOLD SWEEP (>= and <=) ===")
    bull = results[(results["direction"] == "bullish")].sort_values(
        "win_pct", ascending=False
    )
    logger.info("\n%s", bull[avail].head(15).to_string(index=False))

    logger.info("=== COMBINED DIRECTIONAL PORTFOLIOS — top 20 by win%% ===")
    combined = results[results["direction"] == "combined"].sort_values(
        "win_pct", ascending=False
    )
    c_avail = [c for c in report_cols + ["gate_form", "filter_dir"]
               if c in combined.columns]
    logger.info("\n%s", combined[c_avail].head(20).to_string(index=False))

    logger.info("=== TOP 15 OVERALL BY WIN%% (portfolio-level, >= 100 tpy) ===")
    portfolio_level = results[
        (results["direction"].isin(["combined", "bearish", "bullish"]))
        & (results.get("trades_per_year", pd.Series(dtype=float)) >= MIN_TPY)
    ].sort_values("win_pct", ascending=False)
    logger.info("\n%s", portfolio_level[c_avail].head(15).to_string(index=False))

    logger.info("=== REFERENCE POINTS ===")
    logger.info("  no gate (fixed_top15):                   40.71%% win, 267 tpy")
    logger.info("  htf_range_mid>=0.4 (plain):              41.92%% win, 153 tpy")
    logger.info("  bars<=2 & dist>=0.25 (prior best d-2):   43.79%% win, 151 tpy")
    logger.info("  htf_dir>=0.4 & bars<=3 & dist>=0.25:     44.23%% win, 101.5 tpy")


if __name__ == "__main__":
    main()
