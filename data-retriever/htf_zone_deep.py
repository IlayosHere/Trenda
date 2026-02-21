#!/usr/bin/env python3
"""
HTF zone deep gate optimizer.

Extends htf_zone_stack with direction-aware gating:
  - Bearish trades and bullish trades have different optimal filters
  - Key hypothesis: htf_range_position_mid acts differently per direction
    (deeper premium = better for bearish; deeper discount = better for bullish)
  - Fine-grained positional thresholds beyond p25/p50/p75 quantiles

Phase A: Direction-split single gate sweep
  - Find best gate for bearish trades (bull unchanged) → top-20 bear gates
  - Find best gate for bullish trades (bear unchanged) → top-20 bull gates
  - Grid: top-20 bear × top-20 bull → best combined (bear_gate | bull_gate) pairs

Phase B: Universal depth-1 gate on top of best Phase A config

Output:
    analysis/htf_zone_deep_a.csv  — direction-split gate pairs
    analysis/htf_zone_deep_b.csv  — Phase A best + depth-1 universal gate

Usage:
    cd data-retriever
    python htf_zone_deep.py
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

PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
RR: float = 2.0
MIN_TRADES_ABS: int = 15
MIN_TPY_PORTFOLIO: float = 80.0
TOP_DIR_GATES: int = 20

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = BASE_DIR / "htf_zone_breakdown.csv"
DEEP_A_OUT = BASE_DIR / "htf_zone_deep_a.csv"
DEEP_B_OUT = BASE_DIR / "htf_zone_deep_b.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

_EXCLUDE_GATE: set[str] = {
    "id", "entry_signal_id", "signal_time", "symbol", "direction",
    "sl_model", "rr_multiple", "sl_atr", "exit_reason", "return_r",
    "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "hour_of_day_utc", "htf_zone", "_bucket",
    # handled separately via fine-grained thresholds
    "htf_range_position_mid", "htf_range_position_high",
    # constant in this dataset
    "trend_alignment_strength", "trend_age_bars_1h",
}

_DROP_DUPLICATE_COLS: set[str] = {
    "signal_candle_range_atr",   # == break_impulse_range_atr
    "signal_candle_body_atr",    # == break_impulse_body_atr
    "geo_aoi_height_atr",        # == aoi_height_atr
}

# Fine-grained HTF position thresholds (within and across zones)
# Bearish: higher = deeper premium; also tests discount zone cuts
HTF_POS_BEAR: list[tuple[str, float]] = [
    ("htf_pos>=0.78", 0.78), ("htf_pos>=0.80", 0.80),
    ("htf_pos>=0.82", 0.82), ("htf_pos>=0.85", 0.85),
    ("htf_pos>=0.88", 0.88), ("htf_pos>=0.90", 0.90),
    ("htf_pos>=0.50", 0.50), ("htf_pos>=0.60", 0.60),
    ("htf_pos>=0.65", 0.65), ("htf_pos>=0.70", 0.70),
]
# Bullish: lower = deeper discount; also tests premium zone cuts
HTF_POS_BULL: list[tuple[str, float]] = [
    ("htf_pos<=0.22", 0.22), ("htf_pos<=0.20", 0.20),
    ("htf_pos<=0.18", 0.18), ("htf_pos<=0.15", 0.15),
    ("htf_pos<=0.12", 0.12), ("htf_pos<=0.10", 0.10),
    ("htf_pos<=0.50", 0.50), ("htf_pos<=0.40", 0.40),
    ("htf_pos<=0.35", 0.35), ("htf_pos<=0.30", 0.30),
]


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
    gross_profit = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gross_loss = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades": len(df_s),
        "tpy": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(gross_profit / max(gross_loss, 1e-9), 3),
    }


# ---------------------------------------------------------------------------
# Portfolio reconstruction
# ---------------------------------------------------------------------------

def build_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    breakdown = pd.read_csv(BREAKDOWN_CSV)
    best_per_bucket = (
        breakdown
        .sort_values("win_pct", ascending=False)
        .drop_duplicates(subset=["group", "direction", "zone"])
    )
    parts: list[pd.DataFrame] = []
    for _, cfg in best_per_bucket.iterrows():
        group_name: str = cfg["group"]
        window_hours: set[int] = set(ast.literal_eval(str(cfg["window_hours"])))
        bucket_df = df[
            (df["symbol"].isin(EXCLUSIVE_GROUPS[group_name])) &
            (df["direction"] == cfg["direction"]) &
            (df["htf_zone"] == cfg["zone"]) &
            (df["sl_model"] == cfg["sl_model"]) &
            (df["hour_of_day_utc"].isin(window_hours))
        ].copy()
        if len(bucket_df) >= MIN_TRADES_ABS:
            bucket_df["_bucket"] = f"{group_name}|{cfg['direction']}|{cfg['zone']}"
            parts.append(bucket_df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Gate candidate builders
# ---------------------------------------------------------------------------

def build_directional_gate_candidates(
    portfolio_df: pd.DataFrame,
    direction: str,
) -> list[tuple[str, pd.Series]]:
    """Build gate candidates tuned to one direction, thresholds from that direction's data."""
    dir_df = portfolio_df[portfolio_df["direction"] == direction]
    skip = _EXCLUDE_GATE | _DROP_DUPLICATE_COLS
    candidates: list[tuple[str, pd.Series]] = []

    # Numeric columns — quantile thresholds computed from direction-specific subset
    num_cols = [
        c for c in dir_df.select_dtypes(include="number").columns
        if c not in skip
    ]
    for col in num_cols:
        series = dir_df[col].dropna()
        if len(series) < 50:
            continue
        for q in (0.25, 0.50, 0.75):
            thresh = round(float(series.quantile(q)), 2)
            # Masks applied to full portfolio_df (correct index alignment)
            candidates.append((f"{col}>={thresh}", (portfolio_df[col] >= thresh).fillna(False)))
            candidates.append((f"{col}<={thresh}", (portfolio_df[col] <= thresh).fillna(False)))

    # Fine-grained htf_range_position_mid
    if direction == "bearish":
        for label, thresh in HTF_POS_BEAR:
            candidates.append((label, portfolio_df["htf_range_position_mid"] >= thresh))
    else:
        for label, thresh in HTF_POS_BULL:
            candidates.append((label, portfolio_df["htf_range_position_mid"] <= thresh))

    # Categorical
    for col in ["conflicted_tf", "session_directional_bias", "aoi_classification"]:
        if col in portfolio_df.columns:
            candidates.append((f"{col}_null", portfolio_df[col].isna()))
            candidates.append((f"{col}_not_null", portfolio_df[col].notna()))

    return candidates


def build_universal_gate_candidates(portfolio_df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    """Gate candidates applied uniformly to all trades (direction-agnostic)."""
    skip = _EXCLUDE_GATE | _DROP_DUPLICATE_COLS
    candidates: list[tuple[str, pd.Series]] = []

    num_cols = [
        c for c in portfolio_df.select_dtypes(include="number").columns
        if c not in skip
    ]
    for col in num_cols:
        series = portfolio_df[col].dropna()
        if len(series) < 100:
            continue
        for q in (0.25, 0.50, 0.75):
            thresh = round(float(series.quantile(q)), 2)
            candidates.append((f"{col}>={thresh}", (portfolio_df[col] >= thresh).fillna(False)))
            candidates.append((f"{col}<={thresh}", (portfolio_df[col] <= thresh).fillna(False)))

    for col in ["conflicted_tf", "session_directional_bias", "aoi_classification"]:
        if col in portfolio_df.columns:
            candidates.append((f"{col}_null", portfolio_df[col].isna()))
            candidates.append((f"{col}_not_null", portfolio_df[col].notna()))

    return candidates


# ---------------------------------------------------------------------------
# Phase A: Direction-split gate grid search
# ---------------------------------------------------------------------------

def sweep_single_direction_gate(
    portfolio_df: pd.DataFrame,
    direction: str,
    candidates: list[tuple[str, pd.Series]],
    span_years: float,
    baseline_win: float,
) -> list[tuple[str, pd.Series, dict]]:
    """Apply gate to one direction only, hold other direction unchanged."""
    dir_mask = portfolio_df["direction"] == direction
    other_df = portfolio_df[~dir_mask]
    results: list[tuple[str, pd.Series, dict]] = []

    for name, gate_mask in candidates:
        filtered_dir = portfolio_df[dir_mask & gate_mask]
        combined = pd.concat([filtered_dir, other_df], ignore_index=True)
        m = compute_metrics(combined, span_years, MIN_TPY_PORTFOLIO)
        if m and m["win_pct"] > baseline_win:
            results.append((name, gate_mask, m))

    return sorted(results, key=lambda x: x[2]["win_pct"], reverse=True)


def phase_a_grid(
    portfolio_df: pd.DataFrame,
    bear_gates: list[tuple[str, pd.Series, dict]],
    bull_gates: list[tuple[str, pd.Series, dict]],
    span_years: float,
    baseline_win: float,
) -> list[dict]:
    """Grid: top-N bear × top-N bull direction-split gates → combined metrics."""
    rows: list[dict] = []
    bear_dir = portfolio_df["direction"] == "bearish"
    bull_dir = portfolio_df["direction"] == "bullish"

    logger.info(
        "Phase A grid: %d bear × %d bull = %d combos",
        len(bear_gates), len(bull_gates), len(bear_gates) * len(bull_gates),
    )

    for (bn, bm, _), (un, um, _) in product(bear_gates, bull_gates):
        combined_mask = (bear_dir & bm) | (bull_dir & um)
        m = compute_metrics(portfolio_df[combined_mask], span_years, MIN_TPY_PORTFOLIO)
        if m and m["win_pct"] > baseline_win:
            rows.append({
                "bear_gate": bn,
                "bull_gate": un,
                "gate_combined": f"bear[{bn}]  +  bull[{un}]",
                **m,
            })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase B: Universal depth-1 gate on top of best Phase A
# ---------------------------------------------------------------------------

def phase_b_sweep(
    portfolio_df: pd.DataFrame,
    best_phase_a: dict,
    bear_gates: list[tuple[str, pd.Series, dict]],
    bull_gates: list[tuple[str, pd.Series, dict]],
    universal_candidates: list[tuple[str, pd.Series]],
    span_years: float,
) -> list[dict]:
    """Apply best Phase A dir-gate, then sweep universal gates on top."""
    bear_dir = portfolio_df["direction"] == "bearish"
    bull_dir = portfolio_df["direction"] == "bullish"

    # Reconstruct the best Phase A mask
    best_bear_name = best_phase_a["bear_gate"]
    best_bull_name = best_phase_a["bull_gate"]

    best_bear_mask = next((m for n, m, _ in bear_gates if n == best_bear_name), None)
    best_bull_mask = next((m for n, m, _ in bull_gates if n == best_bull_name), None)

    if best_bear_mask is None or best_bull_mask is None:
        logger.warning("Could not reconstruct Phase A masks — skipping Phase B")
        return []

    phase_a_mask = (bear_dir & best_bear_mask) | (bull_dir & best_bull_mask)
    phase_a_df = portfolio_df[phase_a_mask]
    baseline = compute_metrics(phase_a_df, span_years, MIN_TPY_PORTFOLIO)
    if baseline is None:
        return []

    baseline_win = baseline["win_pct"]
    rows: list[dict] = []

    for uni_name, uni_mask in universal_candidates:
        filtered = phase_a_df[uni_mask.reindex(phase_a_df.index, fill_value=False)]
        m = compute_metrics(filtered, span_years, MIN_TPY_PORTFOLIO)
        if m and m["win_pct"] > baseline_win:
            rows.append({
                "bear_gate": best_bear_name,
                "bull_gate": best_bull_name,
                "universal_gate": uni_name,
                **m,
            })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows (RR=%.1f)", span_years, len(df), RR)

    portfolio_df = build_portfolio(df)
    if portfolio_df.empty:
        logger.error("Portfolio empty — run htf_zone_optimizer.py first")
        return

    baseline = compute_metrics(portfolio_df, span_years, MIN_TPY_PORTFOLIO)
    if baseline is None:
        logger.error("Baseline failed")
        return

    logger.info(
        "Portfolio baseline: %d trades | %.1f tpy | win=%.4f | exp=%.4f | mls=%d",
        baseline["n_trades"], baseline["tpy"], baseline["win_pct"],
        baseline["expectancy_r"], baseline["max_losing_streak"],
    )

    bear_count = int((portfolio_df["direction"] == "bearish").sum())
    bull_count = int((portfolio_df["direction"] == "bullish").sum())
    logger.info("Bearish trades: %d | Bullish trades: %d", bear_count, bull_count)

    baseline_win = baseline["win_pct"]
    display_cols = ["bear_gate", "bull_gate", "n_trades", "tpy", "win_pct",
                    "expectancy_r", "max_losing_streak", "profit_factor"]

    # ---------------------------------------------------------------------------
    # Phase A
    # ---------------------------------------------------------------------------
    bear_candidates = build_directional_gate_candidates(portfolio_df, "bearish")
    bull_candidates = build_directional_gate_candidates(portfolio_df, "bullish")
    logger.info(
        "Gate candidates — bear: %d | bull: %d",
        len(bear_candidates), len(bull_candidates),
    )

    logger.info("Sweeping single bear gates (bull fixed)...")
    bear_single = sweep_single_direction_gate(
        portfolio_df, "bearish", bear_candidates, span_years, baseline_win,
    )
    logger.info("Sweeping single bull gates (bear fixed)...")
    bull_single = sweep_single_direction_gate(
        portfolio_df, "bullish", bull_candidates, span_years, baseline_win,
    )

    logger.info("Top 10 single bear gates:")
    for name, _, m in bear_single[:10]:
        logger.info(
            "  bear[%s] → win=%.4f tpy=%.1f mls=%d exp=%.4f",
            name, m["win_pct"], m["tpy"], m["max_losing_streak"], m["expectancy_r"],
        )

    logger.info("Top 10 single bull gates:")
    for name, _, m in bull_single[:10]:
        logger.info(
            "  bull[%s] → win=%.4f tpy=%.1f mls=%d exp=%.4f",
            name, m["win_pct"], m["tpy"], m["max_losing_streak"], m["expectancy_r"],
        )

    if not bear_single or not bull_single:
        logger.warning("Not enough directional gates — try lowering baseline_win")
        return

    top_bear = bear_single[:TOP_DIR_GATES]
    top_bull = bull_single[:TOP_DIR_GATES]

    grid_results = phase_a_grid(portfolio_df, top_bear, top_bull, span_years, baseline_win)

    if grid_results:
        phase_a_df_out = pd.DataFrame(grid_results)
        phase_a_df_out.to_csv(DEEP_A_OUT, index=False)
        logger.info("Saved %d Phase A results → %s", len(phase_a_df_out), DEEP_A_OUT)

        avail_a = [c for c in display_cols if c in phase_a_df_out.columns]
        logger.info("=== PHASE A: TOP 20 DIR-SPLIT COMBOS ===\n%s",
                    phase_a_df_out[avail_a].head(20).to_string(index=False))

        for win_floor, tpy_floor in [(0.48, 100), (0.47, 100), (0.46, 100), (0.45, 100)]:
            pareto = phase_a_df_out[
                (phase_a_df_out["win_pct"] >= win_floor) &
                (phase_a_df_out["tpy"] >= tpy_floor)
            ].sort_values("tpy", ascending=False)
            if not pareto.empty:
                logger.info(
                    "=== PARETO win>=%.2f & tpy>=%.0f (%d configs) ===\n%s",
                    win_floor, tpy_floor, len(pareto),
                    pareto[avail_a].to_string(index=False),
                )
                break

        best_phase_a = grid_results[0]
        logger.info(
            "Best Phase A: bear[%s] + bull[%s] → win=%.4f tpy=%.1f mls=%d",
            best_phase_a["bear_gate"], best_phase_a["bull_gate"],
            best_phase_a["win_pct"], best_phase_a["tpy"],
            best_phase_a["max_losing_streak"],
        )
    else:
        logger.info("Phase A: no dir-split combo improved on baseline %.4f", baseline_win)
        return

    # ---------------------------------------------------------------------------
    # Phase B
    # ---------------------------------------------------------------------------
    logger.info("Phase B: universal gate on top of best Phase A config...")
    universal_candidates = build_universal_gate_candidates(portfolio_df)
    phase_b_results = phase_b_sweep(
        portfolio_df, best_phase_a,
        top_bear, top_bull,
        universal_candidates, span_years,
    )

    if phase_b_results:
        phase_b_df_out = pd.DataFrame(phase_b_results)
        phase_b_df_out.to_csv(DEEP_B_OUT, index=False)
        logger.info("Saved %d Phase B results → %s", len(phase_b_df_out), DEEP_B_OUT)

        b_cols = ["bear_gate", "bull_gate", "universal_gate", "n_trades", "tpy",
                  "win_pct", "expectancy_r", "max_losing_streak", "profit_factor"]
        avail_b = [c for c in b_cols if c in phase_b_df_out.columns]
        logger.info("=== PHASE B: TOP 15 (PHASE A BEST + UNIVERSAL GATE) ===\n%s",
                    phase_b_df_out[avail_b].head(15).to_string(index=False))

        logger.info("=== PHASE B TOP 10 BY EXPECTANCY ===\n%s",
                    phase_b_df_out.sort_values("expectancy_r", ascending=False)
                    [avail_b].head(10).to_string(index=False))
    else:
        logger.info("Phase B: no universal gate improved on Phase A best (%.4f)",
                    best_phase_a["win_pct"])


if __name__ == "__main__":
    main()
