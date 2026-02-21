#!/usr/bin/env python3
"""
Portfolio gate optimizer.

Baseline: ATR1 top-15 portfolio (each symbol trades only in its optimal
contiguous window) — 40.71% win, ~267 trades/yr.

Finds gate combinations that boost win_pct while keeping >= 50% of baseline
trade volume (floor: 133 trades/yr).

Phases:
  1. Single gate sweep — all signal columns at p10..p90, categoricals, ordinals
  2. Depth-2 sweep — all pairs of top-30 single gates
  3. Depth-3 sweep — all triples of top-15 depth-2 winners

Output: analysis/portfolio_gate_results.csv

Usage:
    cd data-retriever
    python portfolio_gate_optimizer.py
"""
from __future__ import annotations

from itertools import combinations
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
MIN_TRADES_ABS: int = 10
BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "portfolio_gate_results.csv"

# ATR1 seed
SEED_SL_MODEL = "SL_ATR_1_0"
SEED_RR = 2.0
SEED_GATE = lambda d: d["break_close_location"] <= 0.921  # noqa: E731

# Top-15 portfolio: symbol -> window hours
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

# Columns that must never be used as gates
_POST_TRADE = frozenset({
    "entry_signal_id", "id", "rr_multiple", "sl_atr",
    "exit_reason", "return_r", "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "signal_time",
})
_RANGE_POS_COLS = frozenset({
    "htf_range_position_mid", "htf_range_position_high",
    "aoi_midpoint_range_position_mid", "aoi_midpoint_range_position_high",
})

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"] == SEED_RR].copy()
    logger.info("Loaded %d rows", len(df))
    return df


def apply_portfolio_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Apply symbol × window filter for the top-15 portfolio."""
    masks = [
        (df["symbol"] == sym) & df["hour_of_day_utc"].isin(hours)
        for sym, hours in PORTFOLIO.items()
    ]
    combined = masks[0]
    for m in masks[1:]:
        combined = combined | m
    return df[combined].copy()


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
    min_tpy: float,
) -> Optional[dict]:
    if len(df) < MIN_TRADES_ABS or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    if tpy < min_tpy:
        return None
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "sl_pct": round(float((df_s["exit_reason"] == "SL").mean()), 4),
        "timeout_pct": round(float((df_s["exit_reason"] == "TIMEOUT").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gp / max(gl, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Gate library — built from full ATR1 base (before portfolio filter)
# to avoid threshold bias from the already-filtered subset
# ---------------------------------------------------------------------------

def build_gate_library(base_df: pd.DataFrame) -> list[dict]:
    """Comprehensive gate library — thresholds from full ATR1 seed subset."""
    gates: list[dict] = []

    # Direction
    gates.append({"name": "bearish_only",
                  "fn": lambda d: d["direction"] == "bearish"})
    gates.append({"name": "bullish_only",
                  "fn": lambda d: d["direction"] == "bullish"})

    # Conflicted TF
    if "conflicted_tf" in base_df.columns:
        gates.append({"name": "no_conflict",
                      "fn": lambda d: d["conflicted_tf"].isnull()})

    # AOI classification
    if "aoi_classification" in base_df.columns:
        for val in base_df["aoi_classification"].dropna().unique():
            gates.append({
                "name": f"aoi_class=={val}",
                "fn": (lambda d, v=val: d["aoi_classification"] == v),
            })

    # Ordinals
    if "trend_alignment_strength" in base_df.columns:
        for t in (2, 3):
            gates.append({
                "name": f"trend_alignment>={t}",
                "fn": (lambda d, tt=t: d["trend_alignment_strength"] >= tt),
            })
    if "aoi_touch_count_since_creation" in base_df.columns:
        for t in (1, 2, 3):
            gates.append({
                "name": f"aoi_touch<={t}",
                "fn": (lambda d, tt=t: d["aoi_touch_count_since_creation"] <= tt),
            })

    # All numeric signal columns at p10/p25/p50/p75/p90
    numeric_cols = [
        c for c in base_df.select_dtypes(include="number").columns
        if c not in _POST_TRADE
        and c not in _RANGE_POS_COLS
        and c not in {"trend_alignment_strength", "aoi_touch_count_since_creation",
                      "hour_of_day_utc"}
    ]
    for col in numeric_cols:
        for pct in (10, 25, 50, 75, 90):
            thresh = float(base_df[col].quantile(pct / 100))
            if np.isnan(thresh):
                continue
            gates.append({
                "name": f"{col}<={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh: d[c] <= t),
            })
            gates.append({
                "name": f"{col}>={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh: d[c] >= t),
            })

    # Direction-aware range position cols
    for col in _RANGE_POS_COLS:
        if col not in base_df.columns:
            continue
        for pct in (10, 25, 50, 75, 90):
            thresh = float(base_df[col].quantile(pct / 100))
            if np.isnan(thresh):
                continue
            gates.append({
                "name": f"bearish_{col}>={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh:
                       (d["direction"] == "bearish") & (d[c] >= t)),
            })
            gates.append({
                "name": f"bullish_{col}<={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh:
                       (d["direction"] == "bullish") & (d[c] <= t)),
            })

    logger.info("Built %d gate candidates", len(gates))
    return gates


# ---------------------------------------------------------------------------
# Sweep helpers
# ---------------------------------------------------------------------------

def _apply(df: pd.DataFrame, gate_fns: list) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for fn in gate_fns:
        mask &= fn(df)
    return df[mask]


def single_sweep(
    port_df: pd.DataFrame,
    gates: list[dict],
    span_years: float,
    baseline_win: float,
    min_tpy: float,
) -> list[dict]:
    rows: list[dict] = []
    for gate in gates:
        try:
            filtered = _apply(port_df, [gate["fn"]])
            m = compute_metrics(filtered, span_years, min_tpy)
            if m:
                rows.append({
                    "depth": 1,
                    "gates": gate["name"],
                    "delta_win": round(m["win_pct"] - baseline_win, 4),
                    "retain_pct": round(m["trades_per_year"] / (baseline_win * 0 + m["trades_per_year"] / m["trades_per_year"]) , 1),  # placeholder
                    **m,
                })
        except Exception:  # noqa: BLE001
            pass
    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


def depth2_sweep(
    port_df: pd.DataFrame,
    top_gates: list[dict],
    span_years: float,
    baseline_win: float,
    min_tpy: float,
) -> list[dict]:
    rows: list[dict] = []
    for g1, g2 in combinations(top_gates, 2):
        try:
            filtered = _apply(port_df, [g1["fn"], g2["fn"]])
            m = compute_metrics(filtered, span_years, min_tpy)
            if m:
                rows.append({
                    "depth": 2,
                    "gates": f"{g1['name']} & {g2['name']}",
                    "delta_win": round(m["win_pct"] - baseline_win, 4),
                    **m,
                })
        except Exception:  # noqa: BLE001
            pass
    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


def depth3_sweep(
    port_df: pd.DataFrame,
    top_gates: list[dict],
    span_years: float,
    baseline_win: float,
    min_tpy: float,
) -> list[dict]:
    rows: list[dict] = []
    for g1, g2, g3 in combinations(top_gates, 3):
        try:
            filtered = _apply(port_df, [g1["fn"], g2["fn"], g3["fn"]])
            m = compute_metrics(filtered, span_years, min_tpy)
            if m:
                rows.append({
                    "depth": 3,
                    "gates": f"{g1['name']} & {g2['name']} & {g3['name']}",
                    "delta_win": round(m["win_pct"] - baseline_win, 4),
                    **m,
                })
        except Exception:  # noqa: BLE001
            pass
    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    # ATR1 seed subset (full, before portfolio filter) — used for gate thresholds
    base_df = df[
        (df["sl_model"] == SEED_SL_MODEL)
        & (df["rr_multiple"] == SEED_RR)
        & SEED_GATE(df)
    ].copy()
    logger.info("ATR1 base: %d rows (%.0f tpy)", len(base_df), len(base_df) / span_years)

    # Apply portfolio filter
    port_df = apply_portfolio_filter(base_df)
    logger.info("Portfolio rows: %d", len(port_df))

    # Baseline metrics
    baseline = compute_metrics(port_df, span_years, min_tpy=1)
    if baseline is None:
        logger.error("Baseline metrics failed.")
        return

    baseline_tpy = baseline["trades_per_year"]
    baseline_win = baseline["win_pct"]
    min_tpy_floor = baseline_tpy * 0.50   # 50% retention floor

    logger.info(
        "Baseline: win=%.4f  tpy=%.1f  exp=%.4f  streak=%d  pf=%.3f",
        baseline_win, baseline_tpy,
        baseline["expectancy_r"], baseline["max_losing_streak"],
        baseline["profit_factor"],
    )
    logger.info("50%% retention floor: %.1f trades/yr", min_tpy_floor)

    # Build gate library from full ATR1 base
    gates = build_gate_library(base_df)

    all_rows: list[dict] = []

    # ------------------------------------------------------------------
    # Phase 1: single gate sweep
    # ------------------------------------------------------------------
    logger.info("Phase 1: single gate sweep (%d gates, floor=%.0f tpy)...",
                len(gates), min_tpy_floor)
    d1 = single_sweep(port_df, gates, span_years, baseline_win, min_tpy_floor)
    improving_d1 = [r for r in d1 if r["delta_win"] > 0]
    all_rows.extend(d1)

    logger.info("Phase 1 done: %d gates pass floor, %d improve win_pct",
                len(d1), len(improving_d1))

    if improving_d1:
        logger.info("=== TOP 20 SINGLE GATES ===")
        _log(improving_d1[:20], baseline_tpy)

    # ------------------------------------------------------------------
    # Phase 2: depth-2 — top 30 single gates (improvers only)
    # ------------------------------------------------------------------
    top30_names = {r["gates"] for r in improving_d1[:30]}
    top30_gate_objs = [g for g in gates if g["name"] in top30_names]

    if len(top30_gate_objs) >= 2:
        logger.info("Phase 2: depth-2 on top-%d gates (%d pairs, floor=%.0f tpy)...",
                    len(top30_gate_objs),
                    len(top30_gate_objs) * (len(top30_gate_objs) - 1) // 2,
                    min_tpy_floor)
        d2 = depth2_sweep(port_df, top30_gate_objs, span_years, baseline_win, min_tpy_floor)
        improving_d2 = [r for r in d2 if r["delta_win"] > 0]
        all_rows.extend(d2)
        logger.info("Phase 2 done: %d pairs pass floor, %d improve win_pct",
                    len(d2), len(improving_d2))
        if improving_d2:
            logger.info("=== TOP 20 DEPTH-2 COMBOS ===")
            _log(improving_d2[:20], baseline_tpy)
    else:
        improving_d2 = []

    # ------------------------------------------------------------------
    # Phase 3: depth-3 — top 15 depth-2 gate objects
    # ------------------------------------------------------------------
    top15_d2_names: set[str] = set()
    for r in improving_d2[:15]:
        for part in r["gates"].split(" & "):
            top15_d2_names.add(part.strip())
    top15_d3_objs = [g for g in gates if g["name"] in top15_d2_names]

    if len(top15_d3_objs) >= 3:
        n_triples = (len(top15_d3_objs) * (len(top15_d3_objs)-1) * (len(top15_d3_objs)-2)) // 6
        logger.info("Phase 3: depth-3 on %d gates (%d triples, floor=%.0f tpy)...",
                    len(top15_d3_objs), n_triples, min_tpy_floor)
        d3 = depth3_sweep(port_df, top15_d3_objs, span_years, baseline_win, min_tpy_floor)
        improving_d3 = [r for r in d3 if r["delta_win"] > 0]
        all_rows.extend(d3)
        logger.info("Phase 3 done: %d triples pass floor, %d improve win_pct",
                    len(d3), len(improving_d3))
        if improving_d3:
            logger.info("=== TOP 20 DEPTH-3 COMBOS ===")
            _log(improving_d3[:20], baseline_tpy)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    if not all_rows:
        logger.error("No results produced.")
        return

    result = (
        pd.DataFrame(all_rows)
        .drop_duplicates(subset=["gates"])
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )
    # Add retention column
    result["retain_pct"] = (result["trades_per_year"] / baseline_tpy * 100).round(1)
    result["delta_win"] = (result["win_pct"] - baseline_win).round(4)

    result.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(result), OUT_PATH)

    improving = result[result["delta_win"] > 0]
    logger.info(
        "=== SUMMARY: %d configs improve win_pct above baseline %.4f ===",
        len(improving), baseline_win,
    )
    cols = ["depth", "gates", "win_pct", "delta_win", "trades_per_year",
            "retain_pct", "expectancy_r", "max_losing_streak", "profit_factor"]
    avail = [c for c in cols if c in improving.columns]
    logger.info("\n%s", improving[avail].head(30).to_string(index=False))

    # Breakout: best per depth
    for depth in (1, 2, 3):
        best = improving[improving["depth"] == depth]
        if not best.empty:
            top = best.iloc[0]
            logger.info(
                "Best depth-%d: win=%.4f (+%.4f)  tpy=%.1f (%.0f%%)  exp=%.4f  streak=%d  | %s",
                depth, top["win_pct"], top["delta_win"],
                top["trades_per_year"], top["retain_pct"],
                top["expectancy_r"], top["max_losing_streak"],
                top["gates"],
            )


def _log(rows: list[dict], baseline_tpy: float) -> None:
    cols = ["depth", "gates", "win_pct", "delta_win",
            "trades_per_year", "expectancy_r", "max_losing_streak", "profit_factor"]
    df = pd.DataFrame(rows)
    df["retain_pct"] = (df["trades_per_year"] / baseline_tpy * 100).round(1)
    avail = [c for c in cols + ["retain_pct"] if c in df.columns]
    logger.info("\n%s", df[avail].to_string(index=False))


if __name__ == "__main__":
    main()
