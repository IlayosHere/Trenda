#!/usr/bin/env python3
"""
HTF zone gate stacker.

Builds on htf_zone_optimizer:
  - Reconstructs portfolio using ALL viable direction×zone buckets
    (not just hypothesis-aligned) using best config per (group, direction, zone)
    from htf_zone_breakdown.csv
  - Sweeps single gates, then stacks top-N at depth-2

Anti-overfitting: groups and windows already fixed by htf_zone_optimizer.
Gate candidates are signal-quality filters only — no hour or symbol cherry-picking.

Output: analysis/htf_zone_stacked.csv

Usage:
    cd data-retriever
    python htf_zone_stack.py
"""
from __future__ import annotations

import ast
from itertools import combinations
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config — zone thresholds must match htf_zone_optimizer.py
# ---------------------------------------------------------------------------

PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
RR: float = 2.0
MIN_TRADES_ABS: int = 15
MIN_TPY_PORTFOLIO: float = 80.0
TOP_SINGLE_GATES: int = 20     # top single gates to combine at depth-2

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = BASE_DIR / "htf_zone_breakdown.csv"
STACKED_OUT = BASE_DIR / "htf_zone_stacked.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

# Columns to exclude from gate candidates
_EXCLUDE_GATE: set[str] = {
    "id", "entry_signal_id", "signal_time", "symbol", "direction",
    "sl_model", "rr_multiple", "sl_atr", "exit_reason", "return_r",
    "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "hour_of_day_utc", "htf_zone",
    "htf_range_position_mid", "htf_range_position_high",
    "_bucket",
    # always >= 0 / constant in this dataset → no discrimination power
    "trend_alignment_strength", "trend_age_bars_1h",
}

# Perfectly correlated duplicates — keep the first, drop the second
_DROP_DUPLICATE_COLS: set[str] = {
    "signal_candle_range_atr",   # == break_impulse_range_atr
    "signal_candle_body_atr",    # == break_impulse_body_atr
    "geo_aoi_height_atr",        # == aoi_height_atr
}


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

def build_portfolio(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Reconstruct portfolio from breakdown CSV — ALL viable buckets, best per (group, dir, zone)."""
    breakdown = pd.read_csv(BREAKDOWN_CSV)
    best_per_bucket = (
        breakdown
        .sort_values("win_pct", ascending=False)
        .drop_duplicates(subset=["group", "direction", "zone"])
    )

    parts: list[pd.DataFrame] = []
    labels: list[str] = []

    for _, cfg in best_per_bucket.iterrows():
        group_name: str = cfg["group"]
        direction: str = cfg["direction"]
        zone: str = cfg["zone"]
        sl_model: str = cfg["sl_model"]
        window_hours: set[int] = set(ast.literal_eval(str(cfg["window_hours"])))

        bucket_df = df[
            (df["symbol"].isin(EXCLUSIVE_GROUPS[group_name])) &
            (df["direction"] == direction) &
            (df["htf_zone"] == zone) &
            (df["sl_model"] == sl_model) &
            (df["hour_of_day_utc"].isin(window_hours))
        ].copy()

        if len(bucket_df) < MIN_TRADES_ABS:
            continue

        label = f"{group_name}|{direction}|{zone}"
        bucket_df["_bucket"] = label
        parts.append(bucket_df)
        labels.append(
            f"  {label}: {cfg['sl_model']}/{cfg['window']}"
            f"  win={cfg['win_pct']:.4f}  tpy={cfg['tpy']:.1f}"
        )

    if not parts:
        return pd.DataFrame(), []

    return pd.concat(parts, ignore_index=True), labels


# ---------------------------------------------------------------------------
# Gate candidates
# ---------------------------------------------------------------------------

def build_gate_candidates(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    skip = _EXCLUDE_GATE | _DROP_DUPLICATE_COLS
    candidates: list[tuple[str, pd.Series]] = []

    num_cols = [
        c for c in df.select_dtypes(include="number").columns
        if c not in skip
    ]
    for col in num_cols:
        series = df[col].dropna()
        if len(series) < 100:
            continue
        for q in (0.25, 0.50, 0.75):
            thresh = round(float(series.quantile(q)), 2)
            candidates.append((f"{col}>={thresh}", (df[col] >= thresh).fillna(False)))
            candidates.append((f"{col}<={thresh}", (df[col] <= thresh).fillna(False)))

    for col in ["conflicted_tf", "session_directional_bias", "aoi_classification"]:
        if col in df.columns:
            candidates.append((f"{col}_null", df[col].isna()))
            candidates.append((f"{col}_not_null", df[col].notna()))

    return candidates


# ---------------------------------------------------------------------------
# Gate sweeps
# ---------------------------------------------------------------------------

def single_gate_sweep(
    portfolio_df: pd.DataFrame,
    candidates: list[tuple[str, pd.Series]],
    span_years: float,
    baseline_win: float,
) -> list[tuple[str, pd.Series, dict]]:
    results: list[tuple[str, pd.Series, dict]] = []
    for name, mask in candidates:
        m = compute_metrics(portfolio_df[mask], span_years, MIN_TPY_PORTFOLIO)
        if m and m["win_pct"] > baseline_win:
            results.append((name, mask, m))
    return sorted(results, key=lambda x: x[2]["win_pct"], reverse=True)


def depth2_sweep(
    portfolio_df: pd.DataFrame,
    top_gates: list[tuple[str, pd.Series, dict]],
    baseline_win: float,
    span_years: float,
) -> list[dict]:
    rows: list[dict] = []
    gate_pairs = list(combinations([(n, m) for n, m, _ in top_gates], 2))
    logger.info("Testing %d depth-2 combinations...", len(gate_pairs))

    for (n1, m1), (n2, m2) in gate_pairs:
        combined = m1 & m2
        m = compute_metrics(portfolio_df[combined], span_years, MIN_TPY_PORTFOLIO)
        if m and m["win_pct"] > baseline_win:
            rows.append({"gate": f"{n1}  &  {n2}", **m})

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows (RR=%.1f)", span_years, len(df), RR)

    portfolio_df, labels = build_portfolio(df)
    if portfolio_df.empty:
        logger.error("Portfolio empty — run htf_zone_optimizer.py first")
        return

    logger.info("Portfolio buckets (%d):", len(labels))
    for lbl in labels:
        logger.info(lbl)

    baseline = compute_metrics(portfolio_df, span_years, MIN_TPY_PORTFOLIO)
    if baseline is None:
        logger.error("Baseline metrics failed")
        return

    logger.info(
        "Baseline (all buckets, no gate): %d trades | %.1f tpy | win=%.4f | exp=%.4f | mls=%d | pf=%.3f",
        baseline["n_trades"], baseline["tpy"], baseline["win_pct"],
        baseline["expectancy_r"], baseline["max_losing_streak"], baseline["profit_factor"],
    )
    baseline_win = baseline["win_pct"]

    # Single gate sweep
    candidates = build_gate_candidates(portfolio_df)
    logger.info("Gate candidates: %d", len(candidates))

    single_results = single_gate_sweep(portfolio_df, candidates, span_years, baseline_win)
    logger.info("Single gates improving on baseline: %d", len(single_results))

    display_cols = ["gate", "n_trades", "tpy", "win_pct", "expectancy_r", "max_losing_streak", "profit_factor"]

    if single_results:
        top_df = pd.DataFrame([{"gate": n, **m} for n, _, m in single_results[:15]])
        avail = [c for c in display_cols if c in top_df.columns]
        logger.info("=== TOP 15 SINGLE GATES ===\n%s", top_df[avail].to_string(index=False))

    # Depth-2 stacking
    top_for_stack = single_results[:TOP_SINGLE_GATES]
    if len(top_for_stack) < 2:
        logger.warning("Not enough single gates to stack (need >= 2)")
        return

    stacked = depth2_sweep(portfolio_df, top_for_stack, baseline_win, span_years)

    if not stacked:
        logger.info("No depth-2 combo improved on baseline win=%.4f", baseline_win)
        return

    stacked_df = pd.DataFrame(stacked)
    stacked_df.to_csv(STACKED_OUT, index=False)
    logger.info("Saved %d stacked results → %s", len(stacked_df), STACKED_OUT)

    avail = [c for c in display_cols if c in stacked_df.columns]

    logger.info("=== TOP 20 DEPTH-2 BY WIN_PCT ===\n%s", stacked_df[avail].head(20).to_string(index=False))

    for win_floor, tpy_floor in [(0.46, 100), (0.45, 100), (0.44, 100), (0.44, 150)]:
        pareto = stacked_df[
            (stacked_df["win_pct"] >= win_floor) &
            (stacked_df["tpy"] >= tpy_floor)
        ].sort_values("tpy", ascending=False)
        if not pareto.empty:
            logger.info(
                "=== PARETO win>=%.2f & tpy>=%.0f (%d configs) ===\n%s",
                win_floor, tpy_floor, len(pareto), pareto[avail].to_string(index=False),
            )
            break
    else:
        logger.info(
            "No depth-2 combo at win>=0.44 & tpy>=100. Best: win=%.4f tpy=%.1f",
            stacked_df["win_pct"].max(),
            stacked_df.loc[stacked_df["win_pct"].idxmax(), "tpy"],
        )

    logger.info(
        "=== TOP 10 BY EXPECTANCY ===\n%s",
        stacked_df.sort_values("expectancy_r", ascending=False)[avail].head(10).to_string(index=False),
    )


if __name__ == "__main__":
    main()
