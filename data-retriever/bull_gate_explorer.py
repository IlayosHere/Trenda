#!/usr/bin/env python3
"""
bull_gate_explorer.py

Focused search for dominant bull-side gates — mirrors what htf_zone_deep.py
found for bears (tc<=3 = +12.79% lift).

Approach:
  - Analyse bull trades in isolation with a relaxed MIN_TPY_BULL floor
    so gates that reduce volume are still visible.
  - Phase A  : single-gate sweep on bull-only  → sorted by bull win%
  - Phase B  : depth-2 grid on top-N bull gates (bull-only)
  - Phase B2 : best bull depth-2 gate also split by htf zone
                (bullish@discount vs bullish@premium behave differently)
  - Phase C  : take best bull gate + tc<=3 bear hard gate → portfolio metrics
  - Phase D  : depth-2 bear×bull grid (tc<=3 bear fixed, top-10 bull gates)

Output:
    analysis/bull_gates_a.csv   — single gate results
    analysis/bull_gates_b.csv   — depth-2 bull-only grid
    analysis/bull_gates_c.csv   — combined bear+bull portfolio metrics

Usage:
    cd data-retriever
    python bull_gate_explorer.py
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

# Bull-only analysis can afford lower floor (one direction = ~half the trades)
MIN_TRADES_ABS: int   = 15
MIN_TPY_BULL: float   = 12.0      # relaxed for direction-only sweep
MIN_TPY_PORTFOLIO: float = 80.0   # for combined bear+bull portfolio

TOP_N_BULL_GATES: int = 20

BASE_DIR      = Path(__file__).parent
ANALYSIS_DIR  = BASE_DIR / "analysis"
SIGNALS_CSV   = ANALYSIS_DIR / "signals.csv"
EXIT_SIM_CSV  = ANALYSIS_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = ANALYSIS_DIR / "htf_zone_breakdown.csv"
OUT_A   = ANALYSIS_DIR / "bull_gates_a.csv"
OUT_B   = ANALYSIS_DIR / "bull_gates_b.csv"
OUT_C   = ANALYSIS_DIR / "bull_gates_c.csv"
ANALYSIS_DIR.mkdir(exist_ok=True)

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

_EXCLUDE: set[str] = {
    "id", "entry_signal_id", "signal_time", "symbol", "direction",
    "sl_model", "rr_multiple", "sl_atr", "exit_reason", "return_r",
    "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "hour_of_day_utc", "htf_zone", "_bucket",
    "htf_range_position_mid", "htf_range_position_high",
    "trend_alignment_strength", "trend_age_bars_1h",
}
_DROP_DUP: set[str] = {
    "signal_candle_range_atr",
    "signal_candle_body_atr",
    "geo_aoi_height_atr",
}

# Fine-grained HTF position for bullish (deeper discount = better bounce)
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

def _mls(exits: list[str]) -> int:
    streak = mx = 0
    for e in exits:
        if e == "SL":
            streak += 1
            mx = max(mx, streak)
        elif e == "TP":
            streak = 0
    return mx


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
        "n_trades":          len(df_s),
        "tpy":               round(tpy, 1),
        "win_pct":           round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r":      round(exp_r, 4),
        "max_losing_streak": _mls(df_s["exit_reason"].tolist()),
        "profit_factor":     round(gp / max(gl, 1e-9), 3),
    }


# ---------------------------------------------------------------------------
# Portfolio reconstruction
# ---------------------------------------------------------------------------

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
        if len(sub) >= MIN_TRADES_ABS:
            sub["_bucket"] = f"{grp}|{cfg['direction']}|{cfg['zone']}"
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Gate candidates — derived purely from bull-direction data
# ---------------------------------------------------------------------------

def build_bull_gate_candidates(
    bull_df: pd.DataFrame,
    full_portfolio_df: pd.DataFrame,
) -> list[tuple[str, pd.Series]]:
    """
    Thresholds computed from bull_df only (direction-aware quantiles).
    Masks apply to full_portfolio_df index for later portfolio combination.
    """
    skip = _EXCLUDE | _DROP_DUP
    candidates: list[tuple[str, pd.Series]] = []

    num_cols = [
        c for c in bull_df.select_dtypes(include="number").columns
        if c not in skip
    ]
    for col in num_cols:
        series = bull_df[col].dropna()
        if len(series) < 50:
            continue
        for q in (0.10, 0.25, 0.50, 0.75, 0.90):
            thresh = round(float(series.quantile(q)), 2)
            # mask on full portfolio (correct index alignment)
            candidates.append((
                f"{col}>={thresh}",
                (full_portfolio_df[col] >= thresh).fillna(False),
            ))
            candidates.append((
                f"{col}<={thresh}",
                (full_portfolio_df[col] <= thresh).fillna(False),
            ))

    # Fine-grained HTF position within discount zone
    for label, thresh in HTF_POS_BULL:
        candidates.append((
            label,
            full_portfolio_df["htf_range_position_mid"] <= thresh,
        ))

    # Categorical nullability
    for col in ["session_directional_bias", "aoi_classification", "conflicted_tf"]:
        if col in full_portfolio_df.columns:
            candidates.append((f"{col}_null",     full_portfolio_df[col].isna()))
            candidates.append((f"{col}_not_null", full_portfolio_df[col].notna()))

    return candidates


# ---------------------------------------------------------------------------
# Phase A — single gate sweep on bull-only trades
# ---------------------------------------------------------------------------

def phase_a_single_gates(
    bull_df: pd.DataFrame,
    candidates: list[tuple[str, pd.Series]],
    span_years: float,
) -> list[dict]:
    baseline = compute_metrics(bull_df, span_years, MIN_TPY_BULL)
    if baseline is None:
        logger.error("Bull baseline failed")
        return []
    baseline_win = baseline["win_pct"]
    logger.info(
        "Bull baseline: %d trades | %.1f tpy | win=%.4f | mls=%d",
        baseline["n_trades"], baseline["tpy"], baseline["win_pct"],
        baseline["max_losing_streak"],
    )

    rows: list[dict] = []
    for name, mask in candidates:
        # restrict mask to bull index
        bull_mask = mask.reindex(bull_df.index, fill_value=False)
        filtered = bull_df[bull_mask]
        m = compute_metrics(filtered, span_years, MIN_TPY_BULL)
        if m is None:
            continue
        rows.append({
            "gate": name,
            "lift": round(m["win_pct"] - baseline_win, 4),
            **m,
        })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase A2 — same but split by htf zone (discount / premium)
# ---------------------------------------------------------------------------

def phase_a2_by_zone(
    bull_df: pd.DataFrame,
    top_gates: list[tuple[str, pd.Series]],  # (name, mask on full portfolio)
    span_years: float,
) -> list[dict]:
    rows: list[dict] = []
    for zone in ("discount", "premium"):
        zone_df = bull_df[bull_df["htf_zone"] == zone]
        base = compute_metrics(zone_df, span_years, MIN_TPY_BULL)
        if base is None:
            continue
        for name, mask in top_gates:
            bull_mask = mask.reindex(zone_df.index, fill_value=False)
            m = compute_metrics(zone_df[bull_mask], span_years, MIN_TPY_BULL)
            if m is None:
                continue
            rows.append({
                "zone": zone,
                "gate": name,
                "lift": round(m["win_pct"] - base["win_pct"], 4),
                "base_win": base["win_pct"],
                **m,
            })
    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase B — depth-2 grid on bull-only (top-N × top-N)
# ---------------------------------------------------------------------------

def phase_b_grid(
    bull_df: pd.DataFrame,
    top_gates: list[tuple[str, pd.Series]],
    span_years: float,
) -> list[dict]:
    baseline = compute_metrics(bull_df, span_years, MIN_TPY_BULL)
    if baseline is None:
        return []
    baseline_win = baseline["win_pct"]

    rows: list[dict] = []
    logger.info(
        "Phase B grid: %d x %d = %d combos",
        len(top_gates), len(top_gates), len(top_gates) ** 2,
    )
    for (n1, m1), (n2, m2) in product(top_gates, top_gates):
        if n1 >= n2:   # skip duplicates and self-pairs
            continue
        bull_mask1 = m1.reindex(bull_df.index, fill_value=False)
        bull_mask2 = m2.reindex(bull_df.index, fill_value=False)
        filtered = bull_df[bull_mask1 & bull_mask2]
        m = compute_metrics(filtered, span_years, MIN_TPY_BULL)
        if m and m["win_pct"] > baseline_win:
            rows.append({
                "gate1": n1,
                "gate2": n2,
                "lift": round(m["win_pct"] - baseline_win, 4),
                **m,
            })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase C — combine best bull gate with tc<=3 bear hard gate → portfolio
# ---------------------------------------------------------------------------

def phase_c_portfolio(
    portfolio_df: pd.DataFrame,
    top_bull_gates: list[tuple[str, pd.Series]],
    span_years: float,
) -> list[dict]:
    bear_dir  = portfolio_df["direction"] == "bearish"
    bull_dir  = portfolio_df["direction"] == "bullish"
    bear_hard = portfolio_df["aoi_touch_count_since_creation"] <= 3.0

    baseline  = compute_metrics(portfolio_df, span_years, MIN_TPY_PORTFOLIO)
    if baseline is None:
        return []
    baseline_win = baseline["win_pct"]
    logger.info(
        "Portfolio baseline (no gate): win=%.4f tpy=%.1f mls=%d",
        baseline["win_pct"], baseline["tpy"], baseline["max_losing_streak"],
    )

    # Bear-only gate baseline (tc<=3, no bull gate)
    bear_only_mask = (bear_dir & bear_hard) | bull_dir
    m_bear_only = compute_metrics(
        portfolio_df[bear_only_mask], span_years, MIN_TPY_PORTFOLIO,
    )
    if m_bear_only:
        logger.info(
            "Bear hard gate only (tc<=3): win=%.4f tpy=%.1f mls=%d",
            m_bear_only["win_pct"], m_bear_only["tpy"], m_bear_only["max_losing_streak"],
        )

    rows: list[dict] = []
    for name, mask in top_bull_gates:
        # Bear: tc<=3 hard gate; Bull: this gate
        combined_mask = (bear_dir & bear_hard) | (bull_dir & mask)
        m = compute_metrics(
            portfolio_df[combined_mask], span_years, MIN_TPY_PORTFOLIO,
        )
        if m is None:
            continue
        # Sub-metrics per direction
        bear_sub = portfolio_df[bear_dir & bear_hard]
        bull_sub  = portfolio_df[bull_dir & mask]
        bm = compute_metrics(bear_sub, span_years, MIN_TPY_BULL)
        um = compute_metrics(bull_sub, span_years, MIN_TPY_BULL)
        rows.append({
            "bull_gate":    name,
            "lift_vs_base": round(m["win_pct"] - baseline_win, 4),
            "bear_win":     bm["win_pct"] if bm else None,
            "bear_tpy":     bm["tpy"]     if bm else None,
            "bull_win":     um["win_pct"] if um else None,
            "bull_tpy":     um["tpy"]     if um else None,
            **m,
        })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase D — depth-2 grid: tc<=3 bear hard + top bull gates (portfolio level)
# ---------------------------------------------------------------------------

def phase_d_bear_bull_grid(
    portfolio_df: pd.DataFrame,
    top_bull_gates: list[tuple[str, pd.Series]],
    span_years: float,
) -> list[dict]:
    bear_dir  = portfolio_df["direction"] == "bearish"
    bull_dir  = portfolio_df["direction"] == "bullish"
    bear_hard = portfolio_df["aoi_touch_count_since_creation"] <= 3.0

    rows: list[dict] = []
    logger.info(
        "Phase D: tc<=3 bear + top-%d bull gates (depth-2 grid)",
        len(top_bull_gates),
    )
    for (n1, m1), (n2, m2) in product(top_bull_gates, top_bull_gates):
        if n1 >= n2:
            continue
        bull_mask = m1.reindex(portfolio_df.index, fill_value=False) \
                  & m2.reindex(portfolio_df.index, fill_value=False)
        combined = portfolio_df[(bear_dir & bear_hard) | (bull_dir & bull_mask)]
        m = compute_metrics(combined, span_years, MIN_TPY_PORTFOLIO)
        if m is None:
            continue
        um = compute_metrics(
            portfolio_df[bull_dir & bull_mask], span_years, MIN_TPY_BULL,
        )
        rows.append({
            "bull_gate1": n1,
            "bull_gate2": n2,
            "bull_win":   um["win_pct"] if um else None,
            "bull_tpy":   um["tpy"]     if um else None,
            **m,
        })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", span_years, len(df))

    portfolio_df = build_portfolio(df)
    if portfolio_df.empty:
        logger.error("Portfolio empty — run htf_zone_optimizer.py first")
        return

    bull_df = portfolio_df[portfolio_df["direction"] == "bullish"].copy()
    bear_df = portfolio_df[portfolio_df["direction"] == "bearish"].copy()
    logger.info(
        "Portfolio: %d total | %d bull | %d bear",
        len(portfolio_df), len(bull_df), len(bear_df),
    )

    # Bear reference (tc<=3 gate on bear alone)
    bear_m = compute_metrics(
        bear_df[bear_df["aoi_touch_count_since_creation"] <= 3.0],
        span_years, MIN_TPY_BULL,
    )
    if bear_m:
        logger.info(
            "Bear reference (tc<=3): win=%.4f tpy=%.1f mls=%d",
            bear_m["win_pct"], bear_m["tpy"], bear_m["max_losing_streak"],
        )

    # ----------------------------------------------------------------
    # Build candidates from bull data
    # ----------------------------------------------------------------
    candidates = build_bull_gate_candidates(bull_df, portfolio_df)
    logger.info("Bull gate candidates: %d", len(candidates))

    # ----------------------------------------------------------------
    # Phase A
    # ----------------------------------------------------------------
    logger.info("=== PHASE A: single gate sweep on bull trades ===")
    a_results = phase_a_single_gates(bull_df, candidates, span_years)

    if a_results:
        a_df = pd.DataFrame(a_results)
        a_df.to_csv(OUT_A, index=False)
        logger.info("Saved %d Phase A results -> %s", len(a_df), OUT_A)

        disp = ["gate", "lift", "n_trades", "tpy", "win_pct",
                "expectancy_r", "max_losing_streak", "profit_factor"]
        avail = [c for c in disp if c in a_df.columns]
        logger.info("=== TOP 30 BULL GATES (by win%%) ===\n%s",
                    a_df[avail].head(30).to_string(index=False))

        # Phase A2: zone split for top gates
        top_gates_for_a2 = [(r["gate"], next(m for n, m in candidates if n == r["gate"]))
                            for r in a_results[:20]
                            if any(n == r["gate"] for n, _ in candidates)]
        if top_gates_for_a2:
            logger.info("=== PHASE A2: zone split (discount vs premium) for top-20 gates ===")
            a2_rows = phase_a2_by_zone(bull_df, top_gates_for_a2, span_years)
            if a2_rows:
                a2_df = pd.DataFrame(a2_rows)
                disp2 = ["zone", "gate", "lift", "base_win", "n_trades", "tpy",
                         "win_pct", "expectancy_r", "max_losing_streak"]
                avail2 = [c for c in disp2 if c in a2_df.columns]
                logger.info("Top 20 by zone:\n%s",
                            a2_df[avail2].head(20).to_string(index=False))
    else:
        logger.warning("Phase A: no bull gates beat baseline")
        return

    # ----------------------------------------------------------------
    # Phase B: depth-2 grid bull-only
    # ----------------------------------------------------------------
    top_for_b = [(r["gate"], next(m for n, m in candidates if n == r["gate"]))
                 for r in a_results[:TOP_N_BULL_GATES]
                 if any(n == r["gate"] for n, _ in candidates)]

    logger.info("=== PHASE B: depth-2 bull-only grid ===")
    b_results = phase_b_grid(bull_df, top_for_b, span_years)

    if b_results:
        b_df = pd.DataFrame(b_results)
        b_df.to_csv(OUT_B, index=False)
        logger.info("Saved %d Phase B results -> %s", len(b_df), OUT_B)
        disp_b = ["gate1", "gate2", "lift", "n_trades", "tpy",
                  "win_pct", "expectancy_r", "max_losing_streak", "profit_factor"]
        avail_b = [c for c in disp_b if c in b_df.columns]
        logger.info("=== TOP 20 DEPTH-2 BULL COMBOS ===\n%s",
                    b_df[avail_b].head(20).to_string(index=False))
    else:
        logger.info("Phase B: no depth-2 combo beat bull baseline")

    # ----------------------------------------------------------------
    # Phase C: portfolio-level — tc<=3 bear hard + each bull gate
    # ----------------------------------------------------------------
    top_for_c = [(r["gate"], next(m for n, m in candidates if n == r["gate"]))
                 for r in a_results[:TOP_N_BULL_GATES]
                 if any(n == r["gate"] for n, _ in candidates)]

    logger.info("=== PHASE C: portfolio — tc<=3 bear + top bull gates ===")
    c_results = phase_c_portfolio(portfolio_df, top_for_c, span_years)

    if c_results:
        c_df = pd.DataFrame(c_results)
        c_df.to_csv(OUT_C, index=False)
        logger.info("Saved %d Phase C results -> %s", len(c_df), OUT_C)
        disp_c = ["bull_gate", "lift_vs_base", "n_trades", "tpy", "win_pct",
                  "expectancy_r", "max_losing_streak", "profit_factor",
                  "bear_win", "bear_tpy", "bull_win", "bull_tpy"]
        avail_c = [c for c in disp_c if c in c_df.columns]
        logger.info("=== TOP 20 PORTFOLIO (tc<=3 bear + bull gate) ===\n%s",
                    c_df[avail_c].head(20).to_string(index=False))

        for win_floor, tpy_floor in [(0.50, 100), (0.49, 100), (0.48, 100), (0.47, 120)]:
            pareto = c_df[
                (c_df["win_pct"] >= win_floor) & (c_df["tpy"] >= tpy_floor)
            ]
            if not pareto.empty:
                logger.info(
                    "=== PARETO win>=%.2f & tpy>=%.0f (%d configs) ===\n%s",
                    win_floor, tpy_floor, len(pareto),
                    pareto[avail_c].head(10).to_string(index=False),
                )
                break
    else:
        logger.info("Phase C: no combos met portfolio criteria")

    # ----------------------------------------------------------------
    # Phase D: depth-2 bull grid at portfolio level
    # ----------------------------------------------------------------
    top_for_d = top_for_c[:10]
    logger.info("=== PHASE D: portfolio — tc<=3 bear + depth-2 bull grid ===")
    d_results = phase_d_bear_bull_grid(portfolio_df, top_for_d, span_years)

    if d_results:
        d_df = pd.DataFrame(d_results)
        disp_d = ["bull_gate1", "bull_gate2", "n_trades", "tpy", "win_pct",
                  "expectancy_r", "max_losing_streak", "profit_factor",
                  "bull_win", "bull_tpy"]
        avail_d = [c for c in disp_d if c in d_df.columns]
        logger.info("=== TOP 20 DEPTH-2 BULL PORTFOLIO COMBOS ===\n%s",
                    d_df[avail_d].head(20).to_string(index=False))

        for win_floor, tpy_floor in [(0.50, 100), (0.49, 100), (0.48, 100)]:
            pareto = d_df[
                (d_df["win_pct"] >= win_floor) & (d_df["tpy"] >= tpy_floor)
            ]
            if not pareto.empty:
                logger.info(
                    "=== PHASE D PARETO win>=%.2f & tpy>=%.0f (%d configs) ===\n%s",
                    win_floor, tpy_floor, len(pareto),
                    pareto[avail_d].head(10).to_string(index=False),
                )
                break
    else:
        logger.info("Phase D: no depth-2 bull combo met portfolio criteria")


if __name__ == "__main__":
    main()
