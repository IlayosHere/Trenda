#!/usr/bin/env python3
"""
System configuration optimizer for Trenda.

Finds (sl_model, rr_multiple, gate_set) combinations that maximize expectancy
subject to: min 100 trades/year and minimized max losing streak.

Usage:
    cd data-retriever
    python analyze_system_config.py [--top-configs N] [--output FILE]
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MIN_TRADES_PER_YEAR: int = 100
MAX_GATE_DEPTH: int = 3
FOCUS_RR: frozenset[float] = frozenset({2.0, 2.5, 3.0})
MAX_GATES_FOR_DEPTH3: int = 30  # cap depth-3 brute-force to avoid explosion

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"].isin(FOCUS_RR)].copy()
    logger.info(
        "Loaded %d rows | %d unique signals | %d (sl_model, rr) combos",
        len(df),
        df["entry_signal_id"].nunique(),
        df.groupby(["sl_model", "rr_multiple"]).ngroups,
    )
    return df


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _max_losing_streak(exits: list[str]) -> int:
    """Only SL exits count as losses. TIMEOUT does not break or extend a streak."""
    streak = max_streak = 0
    for e in exits:
        if e == "SL":
            streak += 1
            if streak > max_streak:
                max_streak = streak
        elif e == "TP":
            streak = 0
        # TIMEOUT: no-op — streak is unaffected
    return max_streak


def compute_metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
    if len(df) < 5 or span_years < 0.01:
        return None
    trades_per_year = len(df) / span_years
    if trades_per_year < MIN_TRADES_PER_YEAR:
        return None
    df_s = df.sort_values("signal_time")
    n = len(df_s)
    win_pct = round(float((df_s["exit_reason"] == "TP").mean()), 4)
    sl_pct = round(float((df_s["exit_reason"] == "SL").mean()), 4)
    timeout_pct = round(float((df_s["exit_reason"] == "TIMEOUT").mean()), 4)
    gross_profit = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gross_loss = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades": n,
        "trades_per_year": round(trades_per_year, 1),
        "win_pct": win_pct,
        "sl_pct": sl_pct,
        "timeout_pct": timeout_pct,
        "expectancy_r": round(float(df_s["return_r"].mean()), 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Phase 1: EDA
# ---------------------------------------------------------------------------

_FEATURE_COLS: tuple[str, ...] = (
    "trend_alignment_strength", "conflicted_tf", "hour_of_day_utc",
    "aoi_touch_count_since_creation", "max_retest_penetration_atr",
    "bars_between_retest_and_break", "htf_range_position_mid",
    "htf_range_position_high", "distance_to_next_htf_obstacle_atr",
    "session_directional_bias", "break_close_location", "break_impulse_range_atr",
    "break_impulse_body_atr", "retest_candle_body_penetration",
    "aoi_last_reaction_strength", "recent_trend_payoff_atr_24h",
    "recent_trend_payoff_atr_48h", "trend_age_bars_1h", "trend_age_impulses",
    "aoi_height_atr", "distance_from_last_impulse_atr", "aoi_time_since_last_touch",
    "htf_range_size_mid_atr", "htf_range_size_high_atr",
    "aoi_midpoint_range_position_mid", "aoi_midpoint_range_position_high",
    "aoi_far_edge_atr", "aoi_near_edge_atr", "geo_aoi_height_atr",
    "signal_candle_opposite_extreme_atr", "signal_candle_range_atr",
    "signal_candle_body_atr",
)


def phase1_eda(df: pd.DataFrame, span_years: float) -> None:
    signals = df.drop_duplicates("entry_signal_id")
    n_signals = len(signals)
    date_min = signals["signal_time"].min()
    date_max = signals["signal_time"].max()

    logger.info("=== Phase 1: EDA ===")
    logger.info(
        "Total signals: %d | Date range: %s → %s (%.2f years) | Signals/year: %.1f",
        n_signals, date_min.date(), date_max.date(), span_years, n_signals / span_years,
    )

    dir_counts = signals["direction"].value_counts()
    logger.info("Direction split:\n%s", dir_counts.to_string())

    existing_cols = [c for c in _FEATURE_COLS if c in signals.columns]
    null_pct = (signals[existing_cols].isnull().mean() * 100).round(1)
    high_null = null_pct[null_pct > 20]
    if not high_null.empty:
        logger.info("Columns >20%% null (flag):\n%s", high_null.to_string())
    else:
        logger.info("No columns with >20%% null")

    exit_dist = df["exit_reason"].value_counts(normalize=True).mul(100).round(1)
    logger.info("Exit distribution (overall):\n%s", exit_dist.to_string())

    exit_per_config = (
        df.groupby(["sl_model", "rr_multiple", "exit_reason"])
        .size()
        .unstack(fill_value=0)
    )
    logger.info("Exit counts per (sl_model, rr_multiple):\n%s", exit_per_config.to_string())

    r_stats = (
        df.groupby("sl_model")["return_r"]
        .describe(percentiles=[0.25, 0.5, 0.75])
        .round(4)
    )
    logger.info("return_r distribution per sl_model:\n%s", r_stats.to_string())


# ---------------------------------------------------------------------------
# Phase 2: Baseline sweep
# ---------------------------------------------------------------------------

def baseline_sweep(df: pd.DataFrame, span_years: float) -> pd.DataFrame:
    results = []
    for (sl_model, rr), group in df.groupby(["sl_model", "rr_multiple"]):
        for direction_filter in ("ALL", "bullish", "bearish"):
            subset = (
                group if direction_filter == "ALL"
                else group[group["direction"] == direction_filter]
            )
            m = compute_metrics(subset, span_years)
            if m:
                results.append({
                    "gate_type": "baseline",
                    "direction_filter": direction_filter,
                    "sl_model": sl_model,
                    "rr_multiple": float(rr),
                    "gates": "none",
                    **m,
                })
    return pd.DataFrame(results).sort_values("expectancy_r", ascending=False)


# ---------------------------------------------------------------------------
# Gate definitions
# ---------------------------------------------------------------------------

def build_gate_candidates(df: pd.DataFrame) -> list[dict]:
    """Build gate candidates from all signal columns.

    Columns coming from exit_simulation (post-trade) are explicitly excluded.
    """
    gates: list[dict] = []

    # Columns that must never be used as gates (post-trade or non-signal metadata)
    _EXCLUDE: frozenset[str] = frozenset({
        "entry_signal_id", "id", "rr_multiple", "sl_atr",
        "exit_reason", "return_r", "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
        "signal_time",
    })

    # Range-position cols need direction-aware treatment instead of plain both-way sweep
    _RANGE_POS_COLS: frozenset[str] = frozenset({
        "htf_range_position_mid", "htf_range_position_high",
        "aoi_midpoint_range_position_mid", "aoi_midpoint_range_position_high",
    })

    # Ordinal cols handled explicitly below
    _ORDINAL: frozenset[str] = frozenset({
        "trend_alignment_strength", "aoi_touch_count_since_creation",
    })

    # Categorical non-numeric cols handled explicitly below
    _CATEGORICAL: frozenset[str] = frozenset({
        "conflicted_tf", "aoi_classification", "symbol", "direction",
    })

    # --- Categoricals ---
    gates.append({"name": "conflicted_tf_is_null",
                  "fn": lambda d: d["conflicted_tf"].isnull()})
    gates.append({"name": "conflicted_tf_is_not_null",
                  "fn": lambda d: d["conflicted_tf"].notnull()})
    for val in df["conflicted_tf"].dropna().unique():
        gates.append({
            "name": f"conflicted_tf=={val!r}",
            "fn": lambda d, v=val: d["conflicted_tf"] == v,
        })

    for cat_col in ("aoi_classification",):
        if cat_col not in df.columns:
            continue
        for val in df[cat_col].dropna().unique():
            gates.append({
                "name": f"{cat_col}=={val!r}",
                "fn": lambda d, c=cat_col, v=val: d[c] == v,
            })
    # Plain symbol gates kept for single-gate sweep baseline visibility
    if "symbol" in df.columns:
        for val in sorted(df["symbol"].dropna().unique()):
            gates.append({
                "name": f"symbol=={val!r}",
                "fn": lambda d, v=val: d["symbol"] == v,
            })

    # --- Ordinals ---
    for thresh in (2, 3):
        gates.append({
            "name": f"trend_alignment_strength>={thresh}",
            "fn": lambda d, t=thresh: d["trend_alignment_strength"] >= t,
        })
    for thresh in (1, 2, 3):
        gates.append({
            "name": f"aoi_touch_count<={thresh}",
            "fn": lambda d, t=thresh: d["aoi_touch_count_since_creation"] <= t,
        })

    # --- All numerical signal columns: sweep >= and <= at p10/p25/p50/p75/p90 ---
    numeric_cols = [
        c for c in df.select_dtypes(include="number").columns
        if c not in _EXCLUDE
        and c not in _RANGE_POS_COLS
        and c not in _ORDINAL
    ]
    for col in numeric_cols:
        for pct in (10, 25, 50, 75, 90):
            thresh = float(df[col].quantile(pct / 100))
            if np.isnan(thresh):
                continue
            gates.append({
                "name": f"{col}>={thresh:.3f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: d[c] >= t,
            })
            gates.append({
                "name": f"{col}<={thresh:.3f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: d[c] <= t,
            })

    # --- Direction-split range-position cols ---
    # Bullish wants low values (near bottom of range), bearish wants high values
    for col in _RANGE_POS_COLS:
        if col not in df.columns:
            continue
        for pct in (10, 25, 50, 75, 90):
            thresh = float(df[col].quantile(pct / 100))
            if np.isnan(thresh):
                continue
            gates.append({
                "name": f"bullish__{col}<={thresh:.3f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: (
                    (d["direction"] == "bullish") & (d[c] <= t)
                ),
            })
            gates.append({
                "name": f"bearish__{col}>={thresh:.3f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: (
                    (d["direction"] == "bearish") & (d[c] >= t)
                ),
            })
            gates.append({
                "name": f"dir_aware__{col}_p{pct}",
                "fn": lambda d, c=col, t=thresh: (
                    ((d["direction"] == "bullish") & (d[c] <= t))
                    | ((d["direction"] == "bearish") & (d[c] >= t))
                ),
            })

    # --- Hour-of-day (standalone) ---
    _SESSIONS: tuple[tuple[str, int, int], ...] = (
        ("asia(0-5)",      0,  5),
        ("london(6-11)",   6, 11),
        ("ny(12-17)",     12, 17),
        ("london_ny(6-17)", 6, 17),
    )
    for sess_name, hs, he in _SESSIONS:
        gates.append({
            "name": sess_name,
            "fn": lambda d, a=hs, b=he: d["hour_of_day_utc"].between(a, b),
        })
    for h in range(24):
        gates.append({
            "name": f"hour=={h}",
            "fn": lambda d, hh=h: d["hour_of_day_utc"] == hh,
        })

    # --- Symbol × session and Symbol × hour combined gates ---
    # Treated as first-class single gates so they participate in depth-2 combos
    # with any feature gate (not requiring depth-3).
    if "symbol" in df.columns:
        for sym in sorted(df["symbol"].dropna().unique()):
            for sess_name, hs, he in _SESSIONS:
                gates.append({
                    "name": f"symbol=={sym!r} & {sess_name}",
                    "fn": lambda d, s=sym, a=hs, b=he: (
                        (d["symbol"] == s) & d["hour_of_day_utc"].between(a, b)
                    ),
                })
            for h in range(24):
                gates.append({
                    "name": f"symbol=={sym!r} & hour=={h}",
                    "fn": lambda d, s=sym, hh=h: (
                        (d["symbol"] == s) & (d["hour_of_day_utc"] == hh)
                    ),
                })

    logger.debug("Built %d gate candidates", len(gates))
    return gates


# ---------------------------------------------------------------------------
# Phase 3: Single-gate sweep
# ---------------------------------------------------------------------------

def single_gate_sweep(
    subset: pd.DataFrame,
    gates: list[dict],
    span_years: float,
    baseline_expectancy: float,
    baseline_n: int,
    baseline_streak: int,
) -> pd.DataFrame:
    results = []
    for gate in gates:
        try:
            filtered = subset[gate["fn"](subset)]
            m = compute_metrics(filtered, span_years)
            if m:
                results.append({
                    "gates": gate["name"],
                    "delta_expectancy": round(m["expectancy_r"] - baseline_expectancy, 4),
                    "trades_retained_pct": round(len(filtered) / max(baseline_n, 1) * 100, 1),
                    "streak_change": m["max_losing_streak"] - baseline_streak,
                    **m,
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("Gate %s skipped: %s", gate["name"], exc)
    return (
        pd.DataFrame(results).sort_values("expectancy_r", ascending=False)
        if results
        else pd.DataFrame()
    )


# ---------------------------------------------------------------------------
# Phase 4a: Greedy gate selection
# ---------------------------------------------------------------------------

def greedy_gate_selection(
    subset: pd.DataFrame,
    gates: list[dict],
    span_years: float,
) -> list[str]:
    """Forward greedy selection. Logs each step; returns ordered gate names added."""
    current_mask = pd.Series(True, index=subset.index)
    current_expectancy = float(subset["return_r"].mean())
    remaining = list(gates)
    added: list[str] = []

    while remaining:
        best_gate = best_m = None
        best_expectancy = current_expectancy
        for gate in remaining:
            try:
                candidate_mask = current_mask & gate["fn"](subset)
                filtered = subset[candidate_mask]
                m = compute_metrics(filtered, span_years)
                if m and m["expectancy_r"] > best_expectancy:
                    best_expectancy = m["expectancy_r"]
                    best_gate = gate
                    best_m = m
            except Exception:  # noqa: BLE001
                pass
        if best_gate is None:
            break
        current_mask = current_mask & best_gate["fn"](subset)
        current_expectancy = best_expectancy
        remaining.remove(best_gate)
        added.append(best_gate["name"])
        assert best_m is not None
        logger.info(
            "  Greedy +%s → expectancy=%.4f  trades/yr=%.1f  streak=%d",
            best_gate["name"], best_m["expectancy_r"],
            best_m["trades_per_year"], best_m["max_losing_streak"],
        )

    return added


# ---------------------------------------------------------------------------
# Phase 4b: Brute-force multi-gate combinations
# ---------------------------------------------------------------------------

def multi_gate_sweep(
    subset: pd.DataFrame,
    top_gates: list[dict],
    span_years: float,
    depth: int = MAX_GATE_DEPTH,
) -> pd.DataFrame:
    results = []
    for d in range(2, depth + 1):
        for combo in combinations(top_gates, d):
            mask = pd.Series(True, index=subset.index)
            for gate in combo:
                mask &= gate["fn"](subset)
            filtered = subset[mask]
            m = compute_metrics(filtered, span_years)
            if m:
                results.append({"gates": " & ".join(g["name"] for g in combo), **m})
    return (
        pd.DataFrame(results).sort_values("expectancy_r", ascending=False)
        if results
        else pd.DataFrame()
    )


# ---------------------------------------------------------------------------
# Analytical questions
# ---------------------------------------------------------------------------

_NUMERICAL_FEATURES: tuple[str, ...] = (
    "trend_alignment_strength", "aoi_touch_count_since_creation",
    "max_retest_penetration_atr", "bars_between_retest_and_break",
    "htf_range_position_mid", "htf_range_position_high",
    "distance_to_next_htf_obstacle_atr", "session_directional_bias",
    "break_close_location", "break_impulse_range_atr", "break_impulse_body_atr",
    "retest_candle_body_penetration", "aoi_last_reaction_strength",
    "recent_trend_payoff_atr_24h", "recent_trend_payoff_atr_48h",
    "trend_age_bars_1h", "trend_age_impulses", "aoi_height_atr",
    "distance_from_last_impulse_atr", "aoi_time_since_last_touch",
    "htf_range_size_mid_atr", "htf_range_size_high_atr",
    "aoi_midpoint_range_position_mid", "aoi_midpoint_range_position_high",
    "signal_candle_opposite_extreme_atr", "signal_candle_range_atr",
    "signal_candle_body_atr",
)


def answer_analytical_questions(df: pd.DataFrame) -> None:
    logger.info("=== Analytical Questions ===")

    # Q1: bullish vs bearish performance
    for dir_ in ("bullish", "bearish"):
        sub = df[df["direction"] == dir_]
        logger.info(
            "Q1 — %s: mean_return_r=%.4f  n_trades=%d",
            dir_, sub["return_r"].mean(), len(sub),
        )

    # Q2: Spearman correlation of features vs return_r
    correlations: list[tuple[str, float]] = []
    for col in _NUMERICAL_FEATURES:
        if col not in df.columns:
            continue
        valid = df[["return_r", col]].dropna()
        if len(valid) < 10:
            continue
        corr, _ = spearmanr(valid["return_r"], valid[col])
        if not np.isnan(corr):
            correlations.append((col, round(float(corr), 4)))
    correlations.sort(key=lambda x: abs(x[1]), reverse=True)
    logger.info("Q2 — Spearman corr (feature vs return_r), top 15:")
    for col, corr in correlations[:15]:
        logger.info("  %-50s  %+.4f", col, corr)

    # Q3: SL model family mean return_r
    sl_stats = (
        df.groupby("sl_model")["return_r"]
        .agg(mean_r="mean", n="count")
        .round(4)
        .sort_values("mean_r", ascending=False)
    )
    logger.info("Q3 — SL model performance:\n%s", sl_stats.to_string())

    # Q4: timeout rate per config
    timeout_rate = (
        df.groupby(["sl_model", "rr_multiple"])
        .apply(lambda g: (g["exit_reason"] == "TIMEOUT").mean())
        .round(3)
        .rename("timeout_rate")
        .sort_values(ascending=False)
    )
    logger.info("Q4 — Timeout rates (top 10 highest):\n%s", timeout_rate.head(10).to_string())

    # Q5: noted inline during Phase 3 single-gate sweep
    logger.info(
        "Q5 — Gates with streak_change < 0 in single-gate output indicate streak reduction."
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_DISPLAY_COLS = [
    "gate_type", "direction_filter", "sl_model", "rr_multiple", "gates",
    "n_trades", "trades_per_year", "win_pct", "sl_pct", "timeout_pct",
    "expectancy_r", "max_losing_streak", "profit_factor",
]


def _log_table(df: pd.DataFrame, n: int = 20) -> None:
    avail = [c for c in _DISPLAY_COLS if c in df.columns]
    logger.info("\n%s", df[avail].head(n).to_string(index=False))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _gate_sweep_for_configs(
    top_baseline: pd.DataFrame,
    df: pd.DataFrame,
    gates: list[dict],
    span_years: float,
    label: str,
) -> list[pd.DataFrame]:
    """Run single + multi gate sweeps for a set of baseline configs. Returns parts list."""
    parts: list[pd.DataFrame] = []
    for idx, (_, row) in enumerate(top_baseline.iterrows()):
        sl_model: str = row["sl_model"]
        rr_multiple: float = row["rr_multiple"]
        baseline_exp: float = row["expectancy_r"]
        baseline_streak: int = int(row["max_losing_streak"])
        subset = df[(df["sl_model"] == sl_model) & (df["rr_multiple"] == rr_multiple)].copy()
        baseline_n = len(subset)

        logger.info("=== [%s] Single-gate  %s  RR=%.2f ===", label, sl_model, rr_multiple)
        single = single_gate_sweep(
            subset, gates, span_years, baseline_exp, baseline_n, baseline_streak,
        )
        if not single.empty:
            _log_table(single, n=10)
            single.insert(0, "gate_type", "single")
            single.insert(0, "direction_filter", "ALL")
            single.insert(0, "rr_multiple", rr_multiple)
            single.insert(0, "sl_model", sl_model)
            parts.append(single)

            positive = single[single["delta_expectancy"] > 0]
            positive_gate_names = set(positive["gates"].tolist())
            all_positive_objs = [g for g in gates if g["name"] in positive_gate_names]
            depth3_names = set(positive.head(MAX_GATES_FOR_DEPTH3)["gates"].tolist())
            depth3_gate_objs = [g for g in gates if g["name"] in depth3_names]

            if len(all_positive_objs) >= 2:
                if idx == 0:
                    logger.info("=== [%s] Greedy  %s  RR=%.2f ===", label, sl_model, rr_multiple)
                    greedy_gate_selection(subset, gates, span_years)

                logger.info(
                    "=== [%s] Multi-gate  %s  RR=%.2f  (d2:%d d3:%d) ===",
                    label, sl_model, rr_multiple,
                    len(all_positive_objs), len(depth3_gate_objs),
                )
                multi_d2 = multi_gate_sweep(
                    subset, all_positive_objs, span_years, depth=2,
                ) if len(all_positive_objs) >= 2 else pd.DataFrame()
                multi_d3 = multi_gate_sweep(
                    subset, depth3_gate_objs, span_years, depth=3,
                ) if len(depth3_gate_objs) >= 3 else pd.DataFrame()
                multi = pd.concat(
                    [x for x in (multi_d2, multi_d3) if not x.empty],
                    ignore_index=True,
                ).sort_values("expectancy_r", ascending=False) if (
                    not multi_d2.empty or not multi_d3.empty
                ) else pd.DataFrame()
                if not multi.empty:
                    _log_table(multi, n=10)
                    multi.insert(0, "gate_type", "multi")
                    multi.insert(0, "direction_filter", "ALL")
                    multi.insert(0, "rr_multiple", rr_multiple)
                    multi.insert(0, "sl_model", sl_model)
                    parts.append(multi)
    return parts


def run_analysis(df: pd.DataFrame, top_configs: int, output_path: str) -> None:
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    gates = build_gate_candidates(df)

    # Phase 1
    phase1_eda(df, span_years)

    # Phase 2: baseline
    logger.info("=== Phase 2: Baseline Sweep ===")
    baseline = baseline_sweep(df, span_years)
    if baseline.empty:
        logger.error("No baseline configs meet minimum %d trades/year", MIN_TRADES_PER_YEAR)
        return
    _log_table(baseline, n=20)

    all_parts: list[pd.DataFrame] = [baseline]

    base_all = baseline[baseline["direction_filter"] == "ALL"]

    # Pass A: top-N by expectancy_r
    top_by_exp = base_all.sort_values("expectancy_r", ascending=False).head(top_configs)
    # Pass B: top-N by win_pct — exclude configs already covered in Pass A
    covered = set(zip(top_by_exp["sl_model"], top_by_exp["rr_multiple"]))
    top_by_win = (
        base_all.sort_values("win_pct", ascending=False)
        .loc[lambda x: ~pd.Series(list(zip(x["sl_model"], x["rr_multiple"])),
                                   index=x.index).isin(covered)]
        .head(top_configs)
    )

    logger.info("=== Phase 3–4: Gate sweeps — Pass A (top by expectancy) ===")
    all_parts += _gate_sweep_for_configs(top_by_exp, df, gates, span_years, "exp")

    logger.info("=== Phase 3–4: Gate sweeps — Pass B (top by win_pct, not in Pass A) ===")
    all_parts += _gate_sweep_for_configs(top_by_win, df, gates, span_years, "win")

    # Analytical questions
    answer_analytical_questions(df)

    # Phase 5: output
    final = (
        pd.concat(all_parts, ignore_index=True)
        .drop_duplicates(subset=["sl_model", "rr_multiple", "gates", "direction_filter"])
        .sort_values("expectancy_r", ascending=False)
    )
    out_cols = [c for c in _DISPLAY_COLS if c in final.columns]
    final[out_cols].to_csv(output_path, index=False)
    logger.info("Saved %d rows → %s", len(final), output_path)

    win_path = output_path.replace(".csv", "_by_winpct.csv")
    (
        final[out_cols]
        .query("trades_per_year >= @MIN_TRADES_PER_YEAR")
        .sort_values("win_pct", ascending=False)
        .to_csv(win_path, index=False)
    )
    logger.info("Saved win_pct-ranked → %s", win_path)

    logger.info("=== TOP 20 BY EXPECTANCY ===")
    _log_table(final, n=20)

    logger.info("=== TOP 20 BY WIN_PCT (positive expectancy only) ===")
    _log_table(
        final[final["expectancy_r"] > 0].sort_values("win_pct", ascending=False),
        n=20,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Trenda system configuration optimizer")
    parser.add_argument(
        "--top-configs", type=int, default=5,
        help="Top baseline configs to run gate sweeps on (default: 5)",
    )
    parser.add_argument(
        "--output", default="analysis/results.csv",
        help="Output CSV path (default: analysis/results.csv)",
    )
    args = parser.parse_args()

    df = load_data()
    if df.empty:
        logger.error("No data loaded — verify CSV files in analysis/")
        sys.exit(1)

    run_analysis(df, top_configs=args.top_configs, output_path=args.output)


if __name__ == "__main__":
    main()
