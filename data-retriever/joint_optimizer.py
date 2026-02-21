#!/usr/bin/env python3
"""
Joint optimizer: pairs × windows × gates.

Jointly searches portfolio composition (which pairs, how many),
window assignment strategy, and clean gates to find Pareto-optimal
configurations that improve win% or tpy without degrading the other.

Rules enforced:
  - Clean gates: round numbers, clear economic logic, max depth=2
  - Logical windows: named contiguous blocks only (no scattered hours)
  - Logical pairs: quality-ranking tiers or named groups (no cherry-picking)
  - Portfolio floor: >= 100 tpy, >= 50 absolute trades
  - Anti-overfitting: min 20 tpy per symbol-window, max 2 gates

Output: analysis/joint_optimizer_results.csv

Usage:
    cd data-retriever
    python joint_optimizer.py
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

MIN_TPY_PORTFOLIO: int = 100
MIN_TPY_SYMBOL: int = 20
MIN_TRADES_ABS: int = 50

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "joint_optimizer_results.csv"

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

PAIR_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors": ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "gbp_pairs":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "EURGBP"],
    "eur_pairs":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "aud_bloc":   ["AUDCAD", "AUDCHF", "AUDJPY", "AUDUSD", "EURAUD", "GBPAUD"],
    "nzd_bloc":   ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD", "EURNZD", "GBPNZD"],
    "high_vol":   ["GBPJPY", "EURJPY", "GBPAUD", "GBPNZD", "EURAUD", "EURNZD"],
}

GateSpec = tuple[str, str, float]

# Clean single gates: (column, operator, threshold) — round numbers only
CLEAN_SINGLE_GATES: list[GateSpec] = [
    ("bars_between_retest_and_break",      "<=", 1),
    ("bars_between_retest_and_break",      "<=", 2),
    ("bars_between_retest_and_break",      "<=", 3),
    ("bars_between_retest_and_break",      "<=", 4),
    ("distance_to_next_htf_obstacle_atr",  ">=", 0.25),
    ("distance_to_next_htf_obstacle_atr",  ">=", 0.5),
    ("distance_to_next_htf_obstacle_atr",  ">=", 0.75),
    ("distance_to_next_htf_obstacle_atr",  ">=", 1.0),
    ("break_close_location",               ">=", 0.5),
    ("break_close_location",               ">=", 0.65),
    ("break_close_location",               ">=", 0.7),
    ("break_close_location",               ">=", 0.75),
    ("signal_candle_opposite_extreme_atr", ">=", 0.25),
    ("signal_candle_opposite_extreme_atr", ">=", 0.35),
    ("signal_candle_opposite_extreme_atr", ">=", 0.5),
    ("max_retest_penetration_atr",         "<=", 0.5),
    ("max_retest_penetration_atr",         "<=", 1.0),
    ("max_retest_penetration_atr",         "<=", 1.25),
    ("max_retest_penetration_atr",         "<=", 1.5),
    ("aoi_far_edge_atr",                   ">=", 1.0),
    ("aoi_far_edge_atr",                   ">=", 1.5),
    ("aoi_far_edge_atr",                   ">=", 2.0),
    ("trend_age_impulses",                 ">=", 3),
    ("trend_age_impulses",                 ">=", 5),
    ("htf_range_size_mid_atr",             ">=", 10),
    ("htf_range_size_mid_atr",             ">=", 15),
    ("htf_range_size_mid_atr",             ">=", 20),
    ("aoi_near_edge_atr",                  ">=", 0.25),
    ("aoi_near_edge_atr",                  ">=", 0.5),
    ("aoi_near_edge_atr",                  ">=", 1.0),
    ("distance_from_last_impulse_atr",     ">=", 0.5),
    ("distance_from_last_impulse_atr",     ">=", 1.0),
    ("distance_from_last_impulse_atr",     ">=", 1.5),
]

# Pre-defined clean 2-gate combos — informed by prior analysis results
CLEAN_2GATE_COMBOS: list[list[GateSpec]] = [
    [("bars_between_retest_and_break",     "<=", 2), ("distance_to_next_htf_obstacle_atr", ">=", 0.25)],
    [("bars_between_retest_and_break",     "<=", 2), ("break_close_location",               ">=", 0.65)],
    [("bars_between_retest_and_break",     "<=", 2), ("signal_candle_opposite_extreme_atr", ">=", 0.35)],
    [("bars_between_retest_and_break",     "<=", 2), ("max_retest_penetration_atr",         "<=", 1.25)],
    [("bars_between_retest_and_break",     "<=", 2), ("aoi_far_edge_atr",                   ">=", 1.5)],
    [("bars_between_retest_and_break",     "<=", 2), ("break_close_location",               ">=", 0.5)],
    [("bars_between_retest_and_break",     "<=", 2), ("aoi_near_edge_atr",                  ">=", 0.25)],
    [("bars_between_retest_and_break",     "<=", 2), ("htf_range_size_mid_atr",             ">=", 10)],
    [("bars_between_retest_and_break",     "<=", 2), ("distance_from_last_impulse_atr",     ">=", 0.5)],
    [("bars_between_retest_and_break",     "<=", 3), ("distance_to_next_htf_obstacle_atr",  ">=", 0.25)],
    [("bars_between_retest_and_break",     "<=", 3), ("break_close_location",               ">=", 0.65)],
    [("bars_between_retest_and_break",     "<=", 3), ("distance_to_next_htf_obstacle_atr",  ">=", 0.5)],
    [("bars_between_retest_and_break",     "<=", 3), ("max_retest_penetration_atr",         "<=", 1.25)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.25), ("break_close_location",            ">=", 0.65)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.5),  ("break_close_location",            ">=", 0.65)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.25), ("max_retest_penetration_atr",      "<=", 1.25)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.25), ("signal_candle_opposite_extreme_atr", ">=", 0.35)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.25), ("aoi_near_edge_atr",               ">=", 0.25)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.25), ("distance_from_last_impulse_atr",  ">=", 0.5)],
    [("break_close_location",              ">=", 0.65), ("max_retest_penetration_atr",       "<=", 1.25)],
    [("break_close_location",              ">=", 0.5),  ("distance_to_next_htf_obstacle_atr",">=", 0.25)],
    [("break_close_location",              ">=", 0.7),  ("max_retest_penetration_atr",       "<=", 1.25)],
    [("aoi_far_edge_atr",                  ">=", 1.5),  ("distance_to_next_htf_obstacle_atr",">=", 0.25)],
    [("aoi_far_edge_atr",                  ">=", 1.5),  ("bars_between_retest_and_break",    "<=", 3)],
    [("max_retest_penetration_atr",        "<=", 1.0),  ("signal_candle_opposite_extreme_atr",">=", 0.5)],
    [("max_retest_penetration_atr",        "<=", 1.25), ("signal_candle_opposite_extreme_atr",">=", 0.35)],
    [("htf_range_size_mid_atr",            ">=", 10),   ("distance_to_next_htf_obstacle_atr",">=", 0.25)],
    [("distance_from_last_impulse_atr",    ">=", 0.5),  ("distance_to_next_htf_obstacle_atr",">=", 0.25)],
    [("aoi_near_edge_atr",                 ">=", 0.25), ("distance_to_next_htf_obstacle_atr",">=", 0.25)],
    [("aoi_near_edge_atr",                 ">=", 0.5),  ("bars_between_retest_and_break",    "<=", 3)],
]

SEEDS: list[dict] = [
    {
        "sl_model": "SL_ATR_1_0",
        "rr_multiple": 2.0,
        "label": "ATR1",
        "gate_fn": lambda d: d["break_close_location"] <= 0.921,
    },
    {
        "sl_model": "SL_SIGNAL_CANDLE",
        "rr_multiple": 2.0,
        "label": "SIG_CANDLE",
        "gate_fn": lambda d: (
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
    min_tpy: float = MIN_TPY_PORTFOLIO,
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
        "sl_pct": round(float((df_s["exit_reason"] == "SL").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------


def apply_gates(df: pd.DataFrame, gates: list[GateSpec]) -> pd.DataFrame:
    for col, op, val in gates:
        if col not in df.columns:
            continue
        if op == "<=":
            df = df[df[col] <= val]
        elif op == ">=":
            df = df[df[col] >= val]
        elif op == "==":
            df = df[df[col] == val]
    return df


def gate_label(gates: list[GateSpec]) -> str:
    if not gates:
        return "no_gate"
    return " & ".join(f"{col}{op}{val}" for col, op, val in gates)


# ---------------------------------------------------------------------------
# Per-symbol window discovery
# ---------------------------------------------------------------------------


def find_best_windows_per_symbol(
    sym_df: pd.DataFrame,
    span_years: float,
    rank_by: str = "win_pct",
) -> list[dict]:
    """All viable contiguous windows for one symbol, sorted by rank_by."""
    results = []
    for win_name, hours in CONTIGUOUS_WINDOWS.items():
        filtered = sym_df[sym_df["hour_of_day_utc"].isin(hours)]
        m = compute_metrics(filtered, span_years, min_tpy=MIN_TPY_SYMBOL)
        if m:
            results.append({"window_name": win_name, "hours": hours, **m})
    return sorted(results, key=lambda r: r[rank_by], reverse=True)


# ---------------------------------------------------------------------------
# Portfolio evaluation
# ---------------------------------------------------------------------------


def build_and_evaluate(
    sym_window_map: dict[str, list[int]],
    base_df: pd.DataFrame,
    span_years: float,
    gates: list[GateSpec],
) -> Optional[dict]:
    parts = [
        base_df[(base_df["symbol"] == sym) & base_df["hour_of_day_utc"].isin(hours)]
        for sym, hours in sym_window_map.items()
    ]
    if not parts:
        return None
    combined = pd.concat(parts, ignore_index=True)
    if gates:
        combined = apply_gates(combined, gates)
    return compute_metrics(combined, span_years)


# ---------------------------------------------------------------------------
# Pareto frontier
# ---------------------------------------------------------------------------


def pareto_frontier(df: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
    """Non-dominated rows maximising both x_col and y_col (O(n log n))."""
    df_s = df.sort_values(x_col, ascending=False).reset_index(drop=True)
    keep: list[pd.Series] = []
    best_y = float("-inf")
    for _, row in df_s.iterrows():
        if row[y_col] >= best_y:
            keep.append(row)
            best_y = row[y_col]
    return pd.DataFrame(keep)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years, %d rows", span_years, len(df))

    all_rows: list[dict] = []

    for seed in SEEDS:
        seed_label = seed["label"]
        base_df = df[
            (df["sl_model"] == seed["sl_model"])
            & (df["rr_multiple"] == seed["rr_multiple"])
            & seed["gate_fn"](df)
        ].copy()

        if base_df.empty:
            logger.warning("[%s] no data after seed filter", seed_label)
            continue

        symbols = sorted(base_df["symbol"].dropna().unique())
        logger.info("[%s] %d symbols, %d rows", seed_label, len(symbols), len(base_df))

        # ── Per-symbol window discovery ──────────────────────────────────────
        sym_data: dict[str, dict] = {}
        for sym in symbols:
            sym_df = base_df[base_df["symbol"] == sym].copy()
            win_ranked = find_best_windows_per_symbol(sym_df, span_years, "win_pct")
            exp_ranked = find_best_windows_per_symbol(sym_df, span_years, "expectancy_r")
            if not win_ranked:
                continue
            sym_data[sym] = {
                "win_ranked": win_ranked,
                "exp_ranked": exp_ranked,
                "best_win_pct": win_ranked[0]["win_pct"],
                "best_exp_r": win_ranked[0]["expectancy_r"],
                "best_tpy": win_ranked[0]["trades_per_year"],
            }

        viable = list(sym_data.keys())
        if not viable:
            continue
        logger.info("[%s] %d viable symbols", seed_label, len(viable))

        # ── Portfolio compositions ───────────────────────────────────────────
        compositions: list[tuple[str, dict[str, list[int]]]] = []

        # A. Top-N by win%: per-symbol best window
        ranked_win = sorted(viable, key=lambda s: sym_data[s]["best_win_pct"], reverse=True)
        for n in [5, 8, 10, 12, 15, 20, len(viable)]:
            n = min(n, len(viable))
            sel = ranked_win[:n]
            compositions.append((
                f"top{n}_win",
                {s: sym_data[s]["win_ranked"][0]["hours"] for s in sel},
            ))

        # A2. Top-N by win%: per-symbol 2nd-best window (robustness check)
        for n in [10, 15, 20]:
            n = min(n, len(viable))
            sel = ranked_win[:n]
            alt = {
                s: (
                    sym_data[s]["win_ranked"][1]["hours"]
                    if len(sym_data[s]["win_ranked"]) > 1
                    else sym_data[s]["win_ranked"][0]["hours"]
                )
                for s in sel
            }
            compositions.append((f"top{n}_win_2ndwin", alt))

        # B. Top-N by expectancy: per-symbol best window (exp-ranked)
        ranked_exp = sorted(viable, key=lambda s: sym_data[s]["best_exp_r"], reverse=True)
        for n in [5, 8, 10, 12, 15, 20, len(viable)]:
            n = min(n, len(viable))
            sel = ranked_exp[:n]
            compositions.append((
                f"top{n}_exp",
                {s: sym_data[s]["exp_ranked"][0]["hours"] for s in sel},
            ))

        # C. Top-N by volume (tpy): per-symbol best window by win%
        ranked_tpy = sorted(viable, key=lambda s: sym_data[s]["best_tpy"], reverse=True)
        for n in [5, 8, 10, 12, 15, 20]:
            n = min(n, len(viable))
            sel = ranked_tpy[:n]
            compositions.append((
                f"top{n}_tpy",
                {s: sym_data[s]["win_ranked"][0]["hours"] for s in sel},
            ))

        # D. Named pair groups × per-symbol best window
        for group_name, group_syms in PAIR_GROUPS.items():
            grp = [s for s in group_syms if s in sym_data]
            if len(grp) < 2:
                continue
            compositions.append((
                f"grp_{group_name}_per_sym",
                {s: sym_data[s]["win_ranked"][0]["hours"] for s in grp},
            ))

        # E. Named pair groups × global named window (all in group → same window)
        for group_name, group_syms in PAIR_GROUPS.items():
            grp = [s for s in group_syms if s in sym_data]
            if len(grp) < 2:
                continue
            for win_name, hours in CONTIGUOUS_WINDOWS.items():
                compositions.append((
                    f"grp_{group_name}_{win_name}",
                    {s: hours for s in grp},
                ))

        # F. All viable symbols × global named window
        for win_name, hours in CONTIGUOUS_WINDOWS.items():
            compositions.append((
                f"all_{win_name}",
                {s: hours for s in viable},
            ))

        logger.info("[%s] %d compositions", seed_label, len(compositions))

        # ── Gate sets ────────────────────────────────────────────────────────
        avail_cols = set(base_df.columns)
        single_gates = [g for g in CLEAN_SINGLE_GATES if g[0] in avail_cols]
        two_gate_combos = [
            combo for combo in CLEAN_2GATE_COMBOS
            if all(g[0] in avail_cols for g in combo)
        ]
        gate_sets: list[list[GateSpec]] = [[]]  # no gate first
        gate_sets.extend([g] for g in single_gates)
        gate_sets.extend(two_gate_combos)

        n_eval = len(compositions) * len(gate_sets)
        logger.info(
            "[%s] %d gate_sets × %d compositions = %d evaluations",
            seed_label, len(gate_sets), len(compositions), n_eval,
        )

        # ── Evaluate ─────────────────────────────────────────────────────────
        for comp_label, sym_window_map in compositions:
            for gates in gate_sets:
                m = build_and_evaluate(sym_window_map, base_df, span_years, gates)
                if m is None:
                    continue
                all_rows.append({
                    "seed": seed_label,
                    "sl_model": seed["sl_model"],
                    "rr_multiple": seed["rr_multiple"],
                    "composition": comp_label,
                    "n_symbols": len(sym_window_map),
                    "gate": gate_label(gates),
                    "n_gates": len(gates),
                    **m,
                })

    if not all_rows:
        logger.warning("No results generated")
        return

    results = pd.DataFrame(all_rows).sort_values(
        ["win_pct", "trades_per_year"], ascending=[False, False]
    )
    results.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(results), OUT_PATH)

    cols = [
        "seed", "composition", "n_symbols", "gate",
        "trades_per_year", "win_pct", "expectancy_r",
        "max_losing_streak", "profit_factor", "n_trades",
    ]
    avail = [c for c in cols if c in results.columns]

    logger.info("=== TOP 40 BY WIN%% ===")
    logger.info("\n%s", results[avail].head(40).to_string(index=False))

    logger.info("=== TOP 20 BY TPY  (win%% >= 0.40) ===")
    high_win = results[results["win_pct"] >= 0.40]
    if not high_win.empty:
        logger.info(
            "\n%s",
            high_win.sort_values("trades_per_year", ascending=False)[avail]
            .head(20).to_string(index=False),
        )

    logger.info("=== PARETO FRONTIER (win%% vs tpy) ===")
    pareto = pareto_frontier(results, "win_pct", "trades_per_year")
    logger.info("\n%s", pareto[avail].to_string(index=False))

    logger.info("=== NO-GATE BASELINES — top 20 by win%% ===")
    no_gate = results[results["n_gates"] == 0].sort_values("win_pct", ascending=False)
    logger.info("\n%s", no_gate[avail].head(20).to_string(index=False))

    # Best per gate-depth to avoid redundant noise
    for depth in [1, 2]:
        subset = results[results["n_gates"] == depth]
        if subset.empty:
            continue
        logger.info("=== TOP 10 DEPTH-%d GATES ===", depth)
        logger.info("\n%s", subset[avail].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
