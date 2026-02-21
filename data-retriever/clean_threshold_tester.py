#!/usr/bin/env python3
"""
Clean threshold tester.

Takes the gate columns found by portfolio_gate_optimizer.py and sweeps
clean, rounded threshold values (not raw percentiles) to find the best
human-readable gate definitions.

Baseline: ATR1 top-15 portfolio = 40.71% win, ~267 trades/yr

Output: analysis/clean_threshold_results.csv

Usage:
    cd data-retriever
    python clean_threshold_tester.py
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MIN_TRADES_ABS: int = 10
BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV  = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH     = BASE_DIR / "clean_threshold_results.csv"

SEED_SL_MODEL = "SL_ATR_1_0"
SEED_RR       = 2.0
SEED_GATE     = lambda d: d["break_close_location"] <= 0.921  # noqa: E731

PORTFOLIO: dict[str, list[int]] = {
    "AUDUSD": list(range(10, 15)),
    "EURNZD": list(range(6,  10)),
    "GBPUSD": list(range(14, 18)),
    "EURJPY": list(range(12, 16)),
    "GBPJPY": list(range(6,  10)),
    "USDJPY": list(range(0,   6)),
    "CADJPY": list(range(6,  10)),
    "NZDJPY": list(range(12, 16)),
    "AUDJPY": list(range(6,  10)),
    "EURUSD": list(range(0,   6)),
    "GBPCAD": list(range(4,   8)),
    "CHFJPY": list(range(12, 16)),
    "USDCHF": list(range(6,  10)),
    "AUDCAD": list(range(14, 18)),
    "GBPNZD": list(range(8,  12)),
}

# ---------------------------------------------------------------------------
# Clean threshold definitions — human-readable sweep values
# ---------------------------------------------------------------------------
CLEAN_SWEEPS: dict[str, list[tuple[str, object]]] = {
    # (operator, value)
    "bars_between_retest_and_break": [
        ("<=", 1), ("<=", 2), ("<=", 3), ("<=", 4),
    ],
    "distance_to_next_htf_obstacle_atr": [
        (">=", 0.1), (">=", 0.2), (">=", 0.25), (">=", 0.3),
        (">=", 0.4), (">=", 0.5), (">=", 0.75), (">=", 1.0),
    ],
    "break_close_location": [
        (">=", 0.3), (">=", 0.4), (">=", 0.5), (">=", 0.6),
        (">=", 0.65), (">=", 0.7), (">=", 0.75), (">=", 0.8),
    ],
    "signal_candle_opposite_extreme_atr": [
        (">=", 0.1), (">=", 0.2), (">=", 0.25), (">=", 0.3),
        (">=", 0.35), (">=", 0.4), (">=", 0.5), (">=", 0.75),
    ],
    "max_retest_penetration_atr": [
        ("<=", 0.25), ("<=", 0.5), ("<=", 0.75), ("<=", 1.0),
        ("<=", 1.25), ("<=", 1.5), ("<=", 2.0),
    ],
    "aoi_far_edge_atr": [
        (">=", 0.5), (">=", 1.0), (">=", 1.25), (">=", 1.5),
        (">=", 2.0), (">=", 2.5), (">=", 3.0),
    ],
    "trend_age_impulses": [
        (">=", 2), (">=", 3), (">=", 4), (">=", 5),
        (">=", 6), (">=", 7), (">=", 8), (">=", 10),
    ],
    "recent_trend_payoff_atr_48h": [
        ("<=", 1.0), ("<=", 1.5), ("<=", 2.0), ("<=", 2.5),
        ("<=", 3.0), ("<=", 4.0), ("<=", 5.0),
    ],
    "htf_range_size_mid_atr": [
        (">=", 10), (">=", 15), (">=", 20), (">=", 25),
        (">=", 30), (">=", 40),
    ],
    "aoi_near_edge_atr": [
        (">=", 0.1), (">=", 0.2), (">=", 0.25), (">=", 0.3),
        (">=", 0.5), (">=", 0.75), (">=", 1.0),
    ],
    "distance_from_last_impulse_atr": [
        (">=", 0.25), (">=", 0.5), (">=", 0.75), (">=", 1.0),
        (">=", 1.25), (">=", 1.5), (">=", 2.0),
    ],
}

# Best known combos from optimizer — rebuilt with clean thresholds to validate
COMBO_GRID: list[list[tuple[str, str, object]]] = [
    # Rank-1 triple (clean)
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("break_close_location", ">=", 0.5)],
    # Rank-2 triple (clean)
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("signal_candle_opposite_extreme_atr", ">=", 0.35)],
    # Rank-3 depth-2 (clean)
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25)],
    # Alternative combos
    [("bars_between_retest_and_break", "<=", 2),
     ("break_close_location", ">=", 0.5)],
    [("bars_between_retest_and_break", "<=", 2),
     ("break_close_location", ">=", 0.6)],
    [("bars_between_retest_and_break", "<=", 2),
     ("max_retest_penetration_atr", "<=", 1.0)],
    [("bars_between_retest_and_break", "<=", 2),
     ("aoi_far_edge_atr", ">=", 1.5)],
    [("bars_between_retest_and_break", "<=", 2),
     ("trend_age_impulses", ">=", 4)],
    [("bars_between_retest_and_break", "<=", 2),
     ("trend_age_impulses", ">=", 5)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("break_close_location", ">=", 0.5)],
    [("distance_to_next_htf_obstacle_atr", ">=", 0.5),
     ("break_close_location", ">=", 0.5)],
    # Triples
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("break_close_location", ">=", 0.6)],
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.5),
     ("break_close_location", ">=", 0.5)],
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("max_retest_penetration_atr", "<=", 1.0)],
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("aoi_far_edge_atr", ">=", 1.5)],
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("trend_age_impulses", ">=", 4)],
    [("bars_between_retest_and_break", "<=", 2),
     ("distance_to_next_htf_obstacle_atr", ">=", 0.25),
     ("trend_age_impulses", ">=", 5)],
]

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits   = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    return df[df["rr_multiple"] == SEED_RR].copy()


def apply_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for sym, hours in PORTFOLIO.items():
        mask |= (df["symbol"] == sym) & df["hour_of_day_utc"].isin(hours)
    return df[mask].copy()


def _max_streak(exits: list[str]) -> int:
    streak = mx = 0
    for e in exits:
        if e == "SL":
            streak += 1; mx = max(mx, streak)
        elif e == "TP":
            streak = 0
    return mx


def metrics(df: pd.DataFrame, span: float, min_tpy: float) -> Optional[dict]:
    if len(df) < MIN_TRADES_ABS or span < 0.01:
        return None
    tpy = len(df) / span
    if tpy < min_tpy:
        return None
    exp = float(df["return_r"].mean())
    if exp <= 0:
        return None
    gp = df.loc[df["return_r"] > 0, "return_r"].sum()
    gl = abs(df.loc[df["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades": len(df),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp, 4),
        "max_losing_streak": _max_streak(df["exit_reason"].tolist()),
        "profit_factor": round(float(gp / max(gl, 1e-9)), 3),
    }


def _apply_gate(df: pd.DataFrame, col: str, op: str, val: object) -> pd.DataFrame:
    if op == "<=":
        return df[df[col] <= val]
    elif op == ">=":
        return df[df[col] >= val]
    elif op == "==":
        return df[df[col] == val]
    raise ValueError(f"Unknown operator: {op}")


def gate_label(col: str, op: str, val: object) -> str:
    return f"{col}{op}{val}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25

    base_df  = df[(df["sl_model"] == SEED_SL_MODEL) & SEED_GATE(df)].copy()
    port_df  = apply_portfolio(base_df)

    base_m = metrics(port_df.sort_values("signal_time"), span, min_tpy=1)
    baseline_tpy = base_m["trades_per_year"]
    baseline_win = base_m["win_pct"]
    floor_tpy    = baseline_tpy * 0.50

    logger.info(
        "Baseline → win=%.4f  tpy=%.1f  exp=%.4f  streak=%d  pf=%.3f",
        baseline_win, baseline_tpy,
        base_m["expectancy_r"], base_m["max_losing_streak"], base_m["profit_factor"],
    )
    logger.info("50%% retention floor: %.0f tpy", floor_tpy)

    rows: list[dict] = []

    # ------------------------------------------------------------------
    # Phase 1: single clean thresholds
    # ------------------------------------------------------------------
    logger.info("Phase 1: single clean threshold sweep...")
    for col, sweep in CLEAN_SWEEPS.items():
        if col not in port_df.columns:
            continue
        for op, val in sweep:
            filtered = _apply_gate(port_df, col, op, val)
            m = metrics(filtered.sort_values("signal_time"), span, min_tpy=floor_tpy)
            if m:
                rows.append({
                    "depth": 1,
                    "gates": gate_label(col, op, val),
                    "delta_win": round(m["win_pct"] - baseline_win, 4),
                    "retain_pct": round(m["trades_per_year"] / baseline_tpy * 100, 1),
                    **m,
                })

    d1_df = pd.DataFrame(rows).sort_values("win_pct", ascending=False)
    logger.info("Phase 1: %d single gates pass floor (%d improve baseline)",
                len(d1_df), (d1_df["delta_win"] > 0).sum())
    if not d1_df.empty:
        logger.info("=== TOP 20 SINGLE CLEAN GATES ===")
        logger.info("\n%s", d1_df[
            ["gates","win_pct","delta_win","trades_per_year","retain_pct",
             "expectancy_r","max_losing_streak","profit_factor"]
        ].head(20).to_string(index=False))

    # ------------------------------------------------------------------
    # Phase 2: pre-defined clean combos
    # ------------------------------------------------------------------
    logger.info("Phase 2: clean combo validation (%d combos)...", len(COMBO_GRID))
    for combo in COMBO_GRID:
        filtered = port_df.copy()
        for col, op, val in combo:
            if col not in filtered.columns:
                break
            filtered = _apply_gate(filtered, col, op, val)
        else:
            m = metrics(filtered.sort_values("signal_time"), span, min_tpy=floor_tpy)
            if m:
                label = " & ".join(gate_label(c, o, v) for c, o, v in combo)
                rows.append({
                    "depth": len(combo),
                    "gates": label,
                    "delta_win": round(m["win_pct"] - baseline_win, 4),
                    "retain_pct": round(m["trades_per_year"] / baseline_tpy * 100, 1),
                    **m,
                })

    # ------------------------------------------------------------------
    # Phase 3: best single gates pairwise (top-15 by win_pct)
    # ------------------------------------------------------------------
    logger.info("Phase 3: pairwise combos from top-15 single gates...")
    top15 = d1_df[d1_df["delta_win"] > 0].head(15)
    top15_gates: list[tuple[str, str, object]] = []
    for gate_str in top15["gates"].tolist():
        for op in ("<=", ">="):
            if op in gate_str:
                col, val_s = gate_str.split(op, 1)
                try:
                    val: object = int(val_s) if val_s.replace(".", "").isdigit() and "." not in val_s else float(val_s)
                except ValueError:
                    val = val_s
                top15_gates.append((col, op, val))
                break

    for (c1, o1, v1), (c2, o2, v2) in combinations(top15_gates, 2):
        if c1 == c2:
            continue
        try:
            filtered = _apply_gate(_apply_gate(port_df, c1, o1, v1), c2, o2, v2)
            m = metrics(filtered.sort_values("signal_time"), span, min_tpy=floor_tpy)
            if m:
                label = f"{gate_label(c1,o1,v1)} & {gate_label(c2,o2,v2)}"
                rows.append({
                    "depth": 2,
                    "gates": label,
                    "delta_win": round(m["win_pct"] - baseline_win, 4),
                    "retain_pct": round(m["trades_per_year"] / baseline_tpy * 100, 1),
                    **m,
                })
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Save & report
    # ------------------------------------------------------------------
    result = (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["gates"])
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )
    result.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(result), OUT_PATH)

    improving = result[result["delta_win"] > 0]
    logger.info("=== ALL IMPROVING CLEAN CONFIGS (sorted by win_pct) ===")
    cols = ["depth","gates","win_pct","delta_win","trades_per_year",
            "retain_pct","expectancy_r","max_losing_streak","profit_factor"]
    avail = [c for c in cols if c in improving.columns]
    logger.info("\n%s", improving[avail].head(40).to_string(index=False))

    logger.info("=== EFFICIENCY FRONTIER ===")
    for label, floor in [(">=90% retain", 0.90), (">=75% retain", 0.75),
                         (">=60% retain", 0.60), (">=50% retain", 0.50)]:
        tier = improving[improving["retain_pct"] >= floor * 100]
        if not tier.empty:
            r = tier.iloc[0]
            logger.info("  %s → win=%.4f  Δ=+%.4f  tpy=%.1f  retain=%.0f%%  streak=%d  | %s",
                        label, r["win_pct"], r["delta_win"],
                        r["trades_per_year"], r["retain_pct"],
                        r["max_losing_streak"], r["gates"])

    logger.info("=== BEST PER DEPTH ===")
    for depth in (1, 2, 3):
        d = improving[improving["depth"] == depth]
        if not d.empty:
            r = d.iloc[0]
            logger.info(
                "  depth-%d → win=%.4f  Δ=+%.4f  tpy=%.1f  retain=%.0f%%  streak=%d  | %s",
                depth, r["win_pct"], r["delta_win"],
                r["trades_per_year"], r["retain_pct"],
                r["max_losing_streak"], r["gates"],
            )


if __name__ == "__main__":
    main()
