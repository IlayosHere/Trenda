#!/usr/bin/env python3
"""
scoring_optimizer.py

Hybrid hard-gate + soft scoring filter.

For each trade:
  direction_score  = sum of direction-specific feature conditions (0..N_BEAR or N_BULL)
  universal_score  = sum of universal feature conditions (0..N_UNI)

Trade passes if:
  hard_gates_ok AND dir_score >= min_dir AND universal_score >= min_uni

Sweep: (bear_hard_label, bull_hard_label, min_dir_score, min_uni_score).

Features used for scoring are the top performers across all prior analysis phases.
Hard-gated features are excluded from direction score (no double-counting).

Output:
    analysis/scoring_results.csv

Usage:
    cd data-retriever
    python scoring_optimizer.py
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

PREMIUM_THRESHOLD: float  = 0.75
DISCOUNT_THRESHOLD: float = 0.25
RR: float         = 2.0
MIN_TRADES_ABS: int   = 15
MIN_TPY: float        = 60.0
TOP_N_RESULTS: int    = 40

BASE_DIR      = Path(__file__).parent
ANALYSIS_DIR  = BASE_DIR / "analysis"
SIGNALS_CSV   = ANALYSIS_DIR / "signals.csv"
EXIT_SIM_CSV  = ANALYSIS_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = ANALYSIS_DIR / "htf_zone_breakdown.csv"
OUT_PATH      = ANALYSIS_DIR / "scoring_results.csv"
ANALYSIS_DIR.mkdir(exist_ok=True)

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

# ---------------------------------------------------------------------------
# Scoring feature definitions
# (column, operator, threshold, label)
#
# BEAR: direction-specific quality signals for bearish trades
# BULL: direction-specific quality signals for bullish trades
# UNIVERSAL: applies to all trades regardless of direction
#
# Thresholds derived from quantile analysis in prior phases — not tuned per run.
# ---------------------------------------------------------------------------

BEAR_SCORE_FEATURES: list[tuple[str, str, float, str]] = [
    ("aoi_touch_count_since_creation",     "<=", 3.0,  "tc<=3"),
    ("aoi_near_edge_atr",                  "<=", 0.32, "near<=0.32"),
    ("break_impulse_range_atr",            "<=", 1.14, "range<=1.14"),
    ("distance_to_next_htf_obstacle_atr",  ">=", 0.21, "dist>=0.21"),
    ("htf_range_size_high_atr",            "<=", 48.0, "htfsize<=48"),
]

BULL_SCORE_FEATURES: list[tuple[str, str, float, str]] = [
    ("session_directional_bias",           ">=", 0.2,  "sbias>=0.2"),
    ("signal_candle_opposite_extreme_atr", "<=", 0.87, "opp<=0.87"),
    ("break_impulse_body_atr",             "<=", 0.64, "body<=0.64"),
    ("aoi_touch_count_since_creation",     "<=", 5.0,  "tc<=5"),
    ("distance_to_next_htf_obstacle_atr",  ">=", 0.21, "dist>=0.21"),
]

UNIVERSAL_SCORE_FEATURES: list[tuple[str, str, float, str]] = [
    ("break_close_location",          "<=", 0.91, "bcl<=0.91"),
    ("bars_between_retest_and_break", "<=", 2.0,  "bars<=2"),
    ("trend_age_impulses",            "<=", 6.0,  "age<=6"),
    ("recent_trend_payoff_atr_24h",   "<=", 2.04, "payoff24<=2.04"),
]

# ---------------------------------------------------------------------------
# Hard gate combos (column, op, threshold)
# Whichever features are hard-gated are excluded from the direction score
# so there is no double-counting.
# ---------------------------------------------------------------------------

BEAR_HARD_OPTIONS: dict[str, list[tuple[str, str, float]]] = {
    "none":                [],
    "tc<=3":               [("aoi_touch_count_since_creation", "<=", 3.0)],
    "tc<=3+dist>=0.21":    [("aoi_touch_count_since_creation", "<=", 3.0),
                             ("distance_to_next_htf_obstacle_atr", ">=", 0.21)],
    "tc<=3+range<=1.14":   [("aoi_touch_count_since_creation", "<=", 3.0),
                             ("break_impulse_range_atr", "<=", 1.14)],
}

BULL_HARD_OPTIONS: dict[str, list[tuple[str, str, float]]] = {
    "none":                [],
    "sbias>=0.2":          [("session_directional_bias", ">=", 0.2)],
    "sbias>=0.2+tc<=5":    [("session_directional_bias", ">=", 0.2),
                             ("aoi_touch_count_since_creation", "<=", 5.0)],
    "sbias>=0.2+opp<=0.87":[("session_directional_bias", ">=", 0.2),
                             ("signal_candle_opposite_extreme_atr", "<=", 0.87)],
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits   = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"] == RR].copy()
    df["htf_zone"] = "mid"
    df.loc[df["htf_range_position_mid"] >= PREMIUM_THRESHOLD,  "htf_zone"] = "premium"
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


def compute_metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
    if len(df) < MIN_TRADES_ABS or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    if tpy < MIN_TPY:
        return None
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades":           len(df_s),
        "tpy":                round(tpy, 1),
        "win_pct":            round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r":       round(exp_r, 4),
        "max_losing_streak":  _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor":      round(gp / max(gl, 1e-9), 3),
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
# Score computation
# ---------------------------------------------------------------------------

def _apply_condition(series: pd.Series, op: str, thresh: float) -> pd.Series:
    if op == "<=":
        return (series <= thresh).fillna(False)
    return (series >= thresh).fillna(False)


def compute_scores(
    df: pd.DataFrame,
    bear_hard_cols: set[str],
    bull_hard_cols: set[str],
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (bear_score, bull_score, uni_score) for every row.
    Hard-gated columns are excluded from direction scores.
    bear_score / bull_score are only meaningful for their respective direction.
    """
    bear_score = pd.Series(0, index=df.index, dtype=int)
    for col, op, thresh, _ in BEAR_SCORE_FEATURES:
        if col in bear_hard_cols or col not in df.columns:
            continue
        bear_score += _apply_condition(df[col], op, thresh).astype(int)

    bull_score = pd.Series(0, index=df.index, dtype=int)
    for col, op, thresh, _ in BULL_SCORE_FEATURES:
        if col in bull_hard_cols or col not in df.columns:
            continue
        bull_score += _apply_condition(df[col], op, thresh).astype(int)

    uni_score = pd.Series(0, index=df.index, dtype=int)
    for col, op, thresh, _ in UNIVERSAL_SCORE_FEATURES:
        if col not in df.columns:
            continue
        uni_score += _apply_condition(df[col], op, thresh).astype(int)

    return bear_score, bull_score, uni_score


def hard_gate_mask(
    df: pd.DataFrame,
    direction: str,
    hard_gates: list[tuple[str, str, float]],
) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for col, op, thresh in hard_gates:
        if col not in df.columns:
            continue
        mask &= _apply_condition(df[col], op, thresh)
    return mask


# ---------------------------------------------------------------------------
# Feature importance report
# ---------------------------------------------------------------------------

def report_feature_importance(
    portfolio_df: pd.DataFrame,
    span_years: float,
) -> None:
    """Win% when each feature is satisfied vs not — on the ungated portfolio."""
    bear_df = portfolio_df[portfolio_df["direction"] == "bearish"]
    bull_df = portfolio_df[portfolio_df["direction"] == "bullish"]

    rows: list[dict] = []
    all_features = (
        [("bear", *f) for f in BEAR_SCORE_FEATURES]
        + [("bull", *f) for f in BULL_SCORE_FEATURES]
        + [("uni",  *f) for f in UNIVERSAL_SCORE_FEATURES]
    )
    for kind, col, op, thresh, label in all_features:
        base_df = bear_df if kind == "bear" else (bull_df if kind == "bull" else portfolio_df)
        if col not in base_df.columns:
            continue
        sat_mask = _apply_condition(base_df[col], op, thresh)
        sat_df  = base_df[sat_mask]
        nsat_df = base_df[~sat_mask]
        m_sat  = compute_metrics(sat_df, span_years)  if len(sat_df)  >= MIN_TRADES_ABS else None
        m_nsat = compute_metrics(nsat_df, span_years) if len(nsat_df) >= MIN_TRADES_ABS else None
        rows.append({
            "direction":    kind,
            "feature":      label,
            "n_sat":        len(sat_df),
            "win_sat":      m_sat["win_pct"]  if m_sat  else None,
            "tpy_sat":      m_sat["tpy"]      if m_sat  else None,
            "n_nsat":       len(nsat_df),
            "win_nsat":     m_nsat["win_pct"] if m_nsat else None,
            "tpy_nsat":     m_nsat["tpy"]     if m_nsat else None,
            "lift":         round((m_sat["win_pct"] - m_nsat["win_pct"]), 4)
                            if m_sat and m_nsat else None,
        })

    imp_df = pd.DataFrame(rows).sort_values("lift", ascending=False)
    logger.info("=== FEATURE IMPORTANCE (win%% lift: satisfied vs not) ===\n%s",
                imp_df.to_string(index=False))


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def sweep(
    portfolio_df: pd.DataFrame,
    span_years: float,
) -> list[dict]:
    bear_dir = portfolio_df["direction"] == "bearish"
    bull_dir = portfolio_df["direction"] == "bullish"

    bear_max = len(BEAR_SCORE_FEATURES)
    bull_max = len(BULL_SCORE_FEATURES)
    uni_max  = len(UNIVERSAL_SCORE_FEATURES)

    rows: list[dict] = []
    total = len(BEAR_HARD_OPTIONS) * len(BULL_HARD_OPTIONS)
    done  = 0

    for (bh_label, bh_gates), (uh_label, uh_gates) in product(
        BEAR_HARD_OPTIONS.items(), BULL_HARD_OPTIONS.items()
    ):
        done += 1
        logger.info(
            "[%d/%d] bear_hard=%s | bull_hard=%s",
            done, total, bh_label, uh_label,
        )

        # Columns covered by hard gates (excluded from scoring)
        bear_hard_cols = {col for col, _, _ in bh_gates}
        bull_hard_cols = {col for col, _, _ in uh_gates}

        bear_score, bull_score, uni_score = compute_scores(
            portfolio_df, bear_hard_cols, bull_hard_cols,
        )

        # Hard gate masks per direction (applied only to that direction)
        bear_hard_ok = hard_gate_mask(portfolio_df, "bearish", bh_gates)
        bull_hard_ok = hard_gate_mask(portfolio_df, "bullish", uh_gates)

        # Available score range after excluding hard-gated features
        avail_bear = bear_max - len([f for f in BEAR_SCORE_FEATURES if f[0] in bear_hard_cols])
        avail_bull = bull_max - len([f for f in BULL_SCORE_FEATURES if f[0] in bull_hard_cols])

        for min_dir, min_uni in product(range(avail_bear + 1), range(uni_max + 1)):
            # Direction-specific thresholds: bear uses min_dir, bull uses min_dir
            # (same threshold for symmetry; avail_bull may differ but scale similarly)
            bear_score_ok = bear_score >= min_dir
            bull_score_ok = bull_score >= min(min_dir, avail_bull)

            bear_pass = bear_dir & bear_hard_ok & bear_score_ok & (uni_score >= min_uni)
            bull_pass = bull_dir & bull_hard_ok & bull_score_ok & (uni_score >= min_uni)
            combined  = portfolio_df[bear_pass | bull_pass]

            m = compute_metrics(combined, span_years)
            if m is None:
                continue

            # Bear and bull sub-metrics
            bm = compute_metrics(combined[combined["direction"] == "bearish"], span_years)
            um = compute_metrics(combined[combined["direction"] == "bullish"], span_years)

            # Effective score label
            bear_feat_labels = [
                lbl for col, _, _, lbl in BEAR_SCORE_FEATURES
                if col not in bear_hard_cols
            ]
            bull_feat_labels = [
                lbl for col, _, _, lbl in BULL_SCORE_FEATURES
                if col not in bull_hard_cols
            ]
            uni_feat_labels = [lbl for *_, lbl in UNIVERSAL_SCORE_FEATURES]

            rows.append({
                "bear_hard":     bh_label,
                "bull_hard":     uh_label,
                "min_dir_score": min_dir,
                "min_uni_score": min_uni,
                "avail_bear":    avail_bear,
                "avail_bull":    avail_bull,
                "avail_uni":     uni_max,
                "bear_features": "|".join(bear_feat_labels),
                "bull_features": "|".join(bull_feat_labels),
                "uni_features":  "|".join(uni_feat_labels),
                "bear_win":      bm["win_pct"] if bm else None,
                "bear_tpy":      bm["tpy"]     if bm else None,
                "bull_win":      um["win_pct"] if um else None,
                "bull_tpy":      um["tpy"]     if um else None,
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

    baseline = compute_metrics(portfolio_df, span_years)
    logger.info(
        "Portfolio baseline: %d trades | %.1f tpy | win=%.4f | exp=%.4f | mls=%d | pf=%.3f",
        baseline["n_trades"], baseline["tpy"], baseline["win_pct"],
        baseline["expectancy_r"], baseline["max_losing_streak"], baseline["profit_factor"],
    )

    report_feature_importance(portfolio_df, span_years)

    results = sweep(portfolio_df, span_years)

    if not results:
        logger.info("No scoring combos met minimum criteria")
        return

    out_df = pd.DataFrame(results)
    out_df.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d results -> %s", len(out_df), OUT_PATH)

    display_cols = [
        "bear_hard", "bull_hard", "min_dir_score", "min_uni_score",
        "n_trades", "tpy", "win_pct", "expectancy_r", "max_losing_streak", "profit_factor",
        "bear_win", "bear_tpy", "bull_win", "bull_tpy",
    ]
    avail = [c for c in display_cols if c in out_df.columns]

    logger.info(
        "=== TOP %d BY WIN PCT ===\n%s",
        TOP_N_RESULTS,
        out_df[avail].head(TOP_N_RESULTS).to_string(index=False),
    )

    for win_floor, tpy_floor in [(0.50, 100), (0.48, 120), (0.47, 140), (0.46, 160)]:
        pareto = out_df[
            (out_df["win_pct"] >= win_floor) & (out_df["tpy"] >= tpy_floor)
        ]
        if not pareto.empty:
            logger.info(
                "=== PARETO win>=%.2f & tpy>=%.0f (%d configs) ===\n%s",
                win_floor, tpy_floor, len(pareto),
                pareto[avail].head(20).to_string(index=False),
            )
            break
    else:
        logger.info(
            "No config met any Pareto target. Best: win=%.4f tpy=%.1f",
            results[0]["win_pct"], results[0]["tpy"],
        )

    # Top by expectancy (volume-quality combined)
    logger.info(
        "=== TOP 15 BY EXPECTANCY_R ===\n%s",
        out_df.sort_values("expectancy_r", ascending=False)[avail]
        .head(15).to_string(index=False),
    )


if __name__ == "__main__":
    main()
