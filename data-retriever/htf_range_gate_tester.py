#!/usr/bin/env python3
"""
HTF range position gate tester.

Tests htf_range_position_mid as a gate — alone and combined with the best
gates from prior analysis — applied to the ATR1 top-15 portfolio and
dynamic top-N portfolio compositions.

Three gate forms for htf_range_position_mid:
  - Plain >=    : all trades (agnostic of direction)
  - Directional : bearish >= X  OR  bullish <= (1 - X)  [economically sound]
  - Combined    : htf directional + existing best single or 2-gate combos

Reference points (fixed top-15, no gate):
  - Baseline (no gate):                       40.71% win, 267 tpy
  - bars_between_retest<=2 & dist>=0.25:      43.79% win, 151 tpy
  - bars<=2 & dist>=0.25 & opp_extreme>=0.35: 44.05% win, 139 tpy

Output: analysis/htf_range_gate_results.csv

Usage:
    cd data-retriever
    python htf_range_gate_tester.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

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
OUT_PATH = BASE_DIR / "htf_range_gate_results.csv"

# ATR1 top-15 fixed portfolio (from prior analysis)
PORTFOLIO: dict[str, list[int]] = {
    "AUDUSD": list(range(10, 15)),  # ld_ny_overlap
    "EURNZD": list(range(6,  10)),  # london_open
    "GBPUSD": list(range(14, 18)),  # ny_afternoon
    "EURJPY": list(range(12, 16)),  # ny_open
    "GBPJPY": list(range(6,  10)),  # london_open
    "USDJPY": list(range(0,  6)),   # asia
    "CADJPY": list(range(6,  10)),  # london_open
    "NZDJPY": list(range(12, 16)),  # ny_open
    "AUDJPY": list(range(6,  10)),  # london_open
    "EURUSD": list(range(0,  6)),   # asia
    "GBPCAD": list(range(4,  8)),   # pre_london
    "CHFJPY": list(range(12, 16)),  # ny_open
    "USDCHF": list(range(6,  10)),  # london_open
    "AUDCAD": list(range(14, 18)),  # ny_afternoon
    "GBPNZD": list(range(8,  12)),  # london_midday
}

CONTIGUOUS_WINDOWS: dict[str, list[int]] = {
    "asia":          list(range(0, 6)),
    "pre_london":    list(range(4, 8)),
    "london_open":   list(range(6, 10)),
    "london":        list(range(6, 12)),
    "london_midday": list(range(8, 12)),
    "ld_ny_overlap": list(range(10, 15)),
    "ny_open":       list(range(12, 16)),
    "ny":            list(range(12, 18)),
    "london_ny":     list(range(6, 18)),
    "ny_afternoon":  list(range(14, 18)),
    "ny_close":      list(range(16, 20)),
    "late_session":  list(range(18, 22)),
    "off_hours":     list(range(20, 24)) + list(range(0, 4)),
}

# Thresholds to sweep for htf_range_position_mid
HTF_THRESHOLDS: list[float] = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

# ---------------------------------------------------------------------------
# Gate types
# ---------------------------------------------------------------------------

FilterFn = Callable[[pd.DataFrame], pd.DataFrame]
Gate = tuple[str, FilterFn]


def _apply_simple(df: pd.DataFrame, col: str, op: str, val: float) -> pd.DataFrame:
    if col not in df.columns:
        return df
    return df[df[col] <= val] if op == "<=" else df[df[col] >= val]


def simple(col: str, op: str, val: float) -> Gate:
    label = f"{col}{op}{val}"
    return label, lambda df, c=col, o=op, v=val: _apply_simple(df, c, o, v)


def htf_plain(threshold: float) -> Gate:
    """htf_range_position_mid >= threshold (all trades, direction-agnostic)."""
    label = f"htf_range_mid>={threshold}"

    def fn(df: pd.DataFrame, _t: float = threshold) -> pd.DataFrame:
        col = "htf_range_position_mid"
        return df[df[col] >= _t] if col in df.columns else df

    return label, fn


def htf_directional(threshold: float) -> Gate:
    """bearish >= threshold  OR  bullish <= (1 - threshold)."""
    label = f"htf_dir>={threshold}"

    def fn(df: pd.DataFrame, _t: float = threshold) -> pd.DataFrame:
        col = "htf_range_position_mid"
        if col not in df.columns or "direction" not in df.columns:
            return df
        mask = (
            ((df["direction"] == "bearish") & (df[col] >= _t))
            | ((df["direction"] == "bullish") & (df[col] <= (1.0 - _t)))
        )
        return df[mask]

    return label, fn


def chain(g1: Gate, g2: Gate) -> Gate:
    return f"{g1[0]} & {g2[0]}", lambda df: g2[1](g1[1](df))


def chain3(g1: Gate, g2: Gate, g3: Gate) -> Gate:
    return chain(chain(g1, g2), g3)


NO_GATE: Gate = ("no_gate", lambda df: df)

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
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------


def build_portfolio(sym_window_map: dict[str, list[int]], base_df: pd.DataFrame) -> pd.DataFrame:
    parts = [
        base_df[(base_df["symbol"] == sym) & base_df["hour_of_day_utc"].isin(hours)]
        for sym, hours in sym_window_map.items()
    ]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def find_best_window_per_symbol(
    sym_df: pd.DataFrame,
    span_years: float,
) -> list[dict]:
    results = []
    for win_name, hours in CONTIGUOUS_WINDOWS.items():
        filtered = sym_df[sym_df["hour_of_day_utc"].isin(hours)]
        m = compute_metrics(filtered, span_years, min_tpy=MIN_TPY_SYMBOL)
        if m:
            results.append({"window_name": win_name, "hours": hours, **m})
    return sorted(results, key=lambda r: r["win_pct"], reverse=True)


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("ATR1 seed: %.2f years, %d rows, %d symbols",
                span_years, len(df), df["symbol"].nunique())

    if "htf_range_position_mid" not in df.columns:
        logger.error("htf_range_position_mid not in data. Columns: %s", list(df.columns))
        return

    stats = df["htf_range_position_mid"].describe()
    logger.info("htf_range_position_mid — min=%.3f  p25=%.3f  p50=%.3f  p75=%.3f  max=%.3f",
                stats["min"], stats["25%"], stats["50%"], stats["75%"], stats["max"])

    if "direction" in df.columns:
        dir_pct = df["direction"].value_counts(normalize=True)
        logger.info("Direction split: %s", dir_pct.to_dict())

    # --- Build fixed portfolio base ---
    fixed_df = build_portfolio(PORTFOLIO, df)
    logger.info("Fixed top-15 portfolio: %d rows", len(fixed_df))

    # --- HTF gate variants ---
    htf_dir_gates = [htf_directional(t) for t in HTF_THRESHOLDS]
    htf_plain_gates = [htf_plain(t) for t in HTF_THRESHOLDS]

    # --- Prior best gates from clean_threshold_tester results ---
    prior_single: list[Gate] = [
        simple("bars_between_retest_and_break",     "<=", 2),
        simple("bars_between_retest_and_break",     "<=", 3),
        simple("distance_to_next_htf_obstacle_atr", ">=", 0.25),
        simple("distance_to_next_htf_obstacle_atr", ">=", 0.5),
        simple("break_close_location",               ">=", 0.65),
        simple("break_close_location",               ">=", 0.5),
        simple("max_retest_penetration_atr",         "<=", 1.25),
        simple("max_retest_penetration_atr",         "<=", 1.0),
        simple("signal_candle_opposite_extreme_atr", ">=", 0.35),
        simple("aoi_far_edge_atr",                   ">=", 1.5),
    ]

    # Prior best 2-gate combos (the known best performing combinations)
    prior_2gate: list[Gate] = [
        chain(simple("bars_between_retest_and_break",     "<=", 2),
              simple("distance_to_next_htf_obstacle_atr", ">=", 0.25)),
        chain(simple("bars_between_retest_and_break",     "<=", 2),
              simple("break_close_location",               ">=", 0.65)),
        chain(simple("bars_between_retest_and_break",     "<=", 2),
              simple("signal_candle_opposite_extreme_atr", ">=", 0.35)),
        chain(simple("bars_between_retest_and_break",     "<=", 2),
              simple("break_close_location",               ">=", 0.5)),
        chain(simple("bars_between_retest_and_break",     "<=", 3),
              simple("distance_to_next_htf_obstacle_atr", ">=", 0.25)),
        chain(simple("distance_to_next_htf_obstacle_atr", ">=", 0.25),
              simple("max_retest_penetration_atr",         "<=", 1.25)),
        chain(simple("break_close_location",               ">=", 0.65),
              simple("max_retest_penetration_atr",         "<=", 1.25)),
        chain(simple("break_close_location",               ">=", 0.7),
              simple("max_retest_penetration_atr",         "<=", 1.25)),
    ]

    all_rows: list[dict] = []

    def record(portfolio_label: str, gate: Gate, port_df: pd.DataFrame) -> None:
        label, fn = gate
        filtered = fn(port_df)
        m = compute_metrics(filtered, span_years)
        if m:
            all_rows.append({
                "portfolio": portfolio_label,
                "gate": label,
                "depth": 0 if label == "no_gate" else label.count(" & ") + 1,
                **m,
            })

    # ==========================================================================
    # FIXED TOP-15 PORTFOLIO
    # ==========================================================================

    # P1: Baseline (no gate)
    record("fixed_top15", NO_GATE, fixed_df)

    # P2: HTF plain >= alone
    for g in htf_plain_gates:
        record("fixed_top15", g, fixed_df)

    # P3: HTF directional alone
    for g in htf_dir_gates:
        record("fixed_top15", g, fixed_df)

    # P4: HTF directional + each prior single gate  (depth-2 total)
    for htf_g in htf_dir_gates:
        for prior_g in prior_single:
            record("fixed_top15", chain(htf_g, prior_g), fixed_df)

    # P5: HTF plain >= + each prior single gate  (depth-2 total)
    for htf_g in htf_plain_gates:
        for prior_g in prior_single:
            record("fixed_top15", chain(htf_g, prior_g), fixed_df)

    # P6: HTF directional + prior 2-gate combos  (depth-3 total)
    for htf_g in htf_dir_gates:
        for two_g in prior_2gate:
            record("fixed_top15", chain(htf_g, two_g), fixed_df)

    # P7: Prior single + HTF directional (reversed order, sanity check — same result)
    # Skip to avoid duplicates — filter functions are commutative in AND logic

    # P8: HTF replacing bars_between_retest (substitution test)
    #     Is htf a stand-in for bars_between_retest or independent signal?
    htf_sub_pairs = [
        ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
        ("distance_to_next_htf_obstacle_atr", ">=", 0.5),
        ("break_close_location",               ">=", 0.65),
        ("max_retest_penetration_atr",         "<=", 1.25),
        ("signal_candle_opposite_extreme_atr", ">=", 0.35),
    ]
    for htf_g in htf_dir_gates:
        for col, op, val in htf_sub_pairs:
            record("fixed_top15", chain(htf_g, simple(col, op, val)), fixed_df)

    logger.info("Fixed portfolio evaluations complete: %d rows so far", len(all_rows))

    # ==========================================================================
    # DYNAMIC TOP-N PORTFOLIOS
    # ==========================================================================

    symbols = sorted(df["symbol"].dropna().unique())
    sym_data: dict[str, dict] = {}
    for sym in symbols:
        rows = find_best_window_per_symbol(df[df["symbol"] == sym].copy(), span_years)
        if rows:
            sym_data[sym] = {"win_ranked": rows, "best_win_pct": rows[0]["win_pct"]}

    viable = sorted(sym_data.keys(), key=lambda s: sym_data[s]["best_win_pct"], reverse=True)

    for n in [5, 8, 10, 12, 15]:
        sel = viable[:min(n, len(viable))]
        port_df = build_portfolio(
            {s: sym_data[s]["win_ranked"][0]["hours"] for s in sel}, df
        )
        label = f"top{n}_win"

        # No gate
        record(label, NO_GATE, port_df)

        # HTF directional alone
        for g in htf_dir_gates:
            record(label, g, port_df)

        # HTF directional + each prior single gate
        for htf_g in htf_dir_gates:
            for prior_g in prior_single:
                record(label, chain(htf_g, prior_g), port_df)

        # HTF directional + prior 2-gate combos (depth-3)
        for htf_g in htf_dir_gates[:5]:  # thresholds 0.4-0.6
            for two_g in prior_2gate:
                record(label, chain(htf_g, two_g), port_df)

    logger.info("Dynamic portfolios complete: %d total rows", len(all_rows))

    # ==========================================================================
    # Save & report
    # ==========================================================================

    if not all_rows:
        logger.warning("No results")
        return

    results = pd.DataFrame(all_rows).sort_values(
        ["win_pct", "trades_per_year"], ascending=[False, False]
    )
    results.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(results), OUT_PATH)

    cols = ["portfolio", "gate", "depth", "trades_per_year", "win_pct",
            "expectancy_r", "max_losing_streak", "profit_factor", "n_trades"]
    avail = [c for c in cols if c in results.columns]

    logger.info("=== TOP 30 BY WIN%% ===")
    logger.info("\n%s", results[avail].head(30).to_string(index=False))

    logger.info("=== TOP 15 BY TPY  (win%% >= 0.42) ===")
    high = results[results["win_pct"] >= 0.42]
    if not high.empty:
        logger.info(
            "\n%s",
            high.sort_values("trades_per_year", ascending=False)[avail]
            .head(15).to_string(index=False),
        )

    logger.info("=== HTF GATES ALONE (fixed_top15 only, no & ) ===")
    htf_only = results[
        (results["portfolio"] == "fixed_top15")
        & (results["gate"].str.startswith("htf"))
        & ~results["gate"].str.contains("&")
    ]
    if not htf_only.empty:
        logger.info("\n%s", htf_only[avail].to_string(index=False))

    logger.info("=== REFERENCE POINTS ===")
    logger.info("  no gate (fixed_top15):                   40.71%% win, 267 tpy")
    logger.info("  bars<=2 & dist>=0.25  (depth-2):         43.79%% win, 151 tpy")
    logger.info("  bars<=2 & dist>=0.25 & opp>=0.35 (d-3):  44.05%% win, 139 tpy")

    logger.info("=== BEST HTF-CONTAINING RESULT ===")
    htf_results = results[results["gate"].str.contains("htf")]
    if not htf_results.empty:
        best = htf_results.iloc[0]
        logger.info("  portfolio=%s  gate=%s  win=%.4f  tpy=%.1f  exp=%.4f",
                    best["portfolio"], best["gate"],
                    best["win_pct"], best["trades_per_year"], best["expectancy_r"])


if __name__ == "__main__":
    main()
