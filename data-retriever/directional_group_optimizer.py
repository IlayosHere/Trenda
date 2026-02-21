#!/usr/bin/env python3
"""
Directional group optimizer.

For each exclusive pair group, runs a three-phase search:

  Phase 1 — Screen: sweep ALL SL models × ALL windows, find top-3
            (SL, window) candidates per group by no-gate win_pct.

  Phase 2 — Directional gates: for each candidate, split trades by
            direction (bearish / bullish) and discover the best gate
            for each direction independently, using ALL numeric columns
            in signals.csv (including unexplored ones).
            Thresholds computed from the full group data (direction-
            specific, p25/p50/p75), not from the filtered window slice,
            to avoid threshold look-ahead bias.
            Also tests direction-specific SL models (Phase 2b):
            bearish trades may use a different SL model than bullish.

  Phase 3 — Combine: union all groups' best directional configs into
            a single portfolio and report metrics.

Anti-overfitting:
  - Group definitions: fundamental (not backtest-derived)
  - One (SL, window, bear_gate, bull_gate) per GROUP (not per symbol)
  - Gate thresholds from full-group data (pre-window-filter)
  - Max gate depth 1 per direction
  - Min 20 tpy per direction for gate selection
  - Min 100 tpy combined portfolio

Output:
    analysis/dir_group_breakdown.csv  — per-group best config
    analysis/dir_group_results.csv    — combined portfolio stats

Usage:
    cd data-retriever
    python directional_group_optimizer.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import core.env  # noqa: F401
import numpy as np
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RR_VALUE: float = 2.0
TOP_SL_CANDIDATES: int = 3     # SL models per group carried from Phase 1 → 2
TOP_WINDOWS_PER_SL: int = 3    # windows per SL model carried into Phase 2
TOP_DIR_GATES: int = 10        # top gates per direction tried in combinations
MIN_TPY_PHASE1: float = 30.0   # per-group phase-1 floor
MIN_TPY_DIR: float = 20.0      # per-direction floor (phase 2)
MIN_TPY_COMBINED: float = 100.0  # combined portfolio floor

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_PATH = BASE_DIR / "dir_group_breakdown.csv"
RESULTS_PATH = BASE_DIR / "dir_group_results.csv"

# Post-trade / ID columns — never used as gates
_EXCLUDE = frozenset({
    "id", "entry_signal_id", "rr_multiple", "sl_atr",
    "exit_reason", "return_r", "bars_to_tp_hit", "bars_to_sl_hit",
    "exit_bar", "signal_time", "symbol", "sl_model",
    "direction", "hour_of_day_utc", "_group",
})

# Ordinal integer columns — use integer thresholds only
_ORDINAL_INT = frozenset({
    "bars_between_retest_and_break", "trend_age_impulses",
    "trend_alignment_strength", "aoi_touch_count_since_creation",
    "trend_age_bars_1h",
})

# Categorical columns handled separately
_CATEGORICAL = frozenset({
    "aoi_classification", "session_directional_bias",
})

# ---------------------------------------------------------------------------
# Exclusive pair groups
# ---------------------------------------------------------------------------

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------

WINDOW_LENGTHS: list[int] = [3, 4, 5, 6, 8, 10]
NAMED_WINDOWS: dict[str, list[int]] = {
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


def generate_windows() -> dict[str, list[int]]:
    windows: dict[str, list[int]] = {}
    seen: set[tuple[int, ...]] = set()
    for start in range(24):
        for length in WINDOW_LENGTHS:
            hours = [(start + i) % 24 for i in range(length)]
            key = tuple(hours)
            if key not in seen:
                seen.add(key)
                windows[f"h{start:02d}+{length}h"] = hours
    for name, hours in NAMED_WINDOWS.items():
        key = tuple(hours)
        if key not in seen:
            seen.add(key)
            windows[name] = hours
    return windows


# ---------------------------------------------------------------------------
# Gate types
# ---------------------------------------------------------------------------

GateFn = Callable[[pd.DataFrame], pd.DataFrame]
Gate = tuple[str, GateFn]

NO_GATE: Gate = ("no_gate", lambda df: df)


def _num_gate(col: str, op: str, val: float) -> Gate:
    label = f"{col}{op}{val}"
    def fn(df: pd.DataFrame, c: str = col, o: str = op, v: float = val) -> pd.DataFrame:
        if c not in df.columns:
            return df
        return df[df[c] <= v] if o == "<=" else df[df[c] >= v]
    return label, fn


def _cat_gate(col: str, val: str) -> Gate:
    label = f"{col}=={val}"
    def fn(df: pd.DataFrame, c: str = col, v: str = val) -> pd.DataFrame:
        return df[df[c] == v] if c in df.columns else df
    return label, fn


def _null_gate(col: str) -> Gate:
    label = f"{col}_is_null"
    def fn(df: pd.DataFrame, c: str = col) -> pd.DataFrame:
        return df[df[c].isnull()] if c in df.columns else df
    return label, fn


def _notnull_gate(col: str) -> Gate:
    label = f"{col}_not_null"
    def fn(df: pd.DataFrame, c: str = col) -> pd.DataFrame:
        return df[df[c].notna()] if c in df.columns else df
    return label, fn


# ---------------------------------------------------------------------------
# Gate library: build from ALL signal columns, direction-specific thresholds
# ---------------------------------------------------------------------------


def build_dir_gate_library(
    group_df: pd.DataFrame,
) -> dict[str, list[Gate]]:
    """
    Build a gate candidate list for each direction using ALL available
    signal columns.  Thresholds computed from the direction-specific subset
    of the full group data (pre-window filter) at p25/p50/p75, rounded to
    2 decimal places.
    """
    result: dict[str, list[Gate]] = {"bearish": [], "bullish": []}

    # Numeric columns (continuous + ordinal)
    num_cols = [
        c for c in group_df.select_dtypes(include="number").columns
        if c not in _EXCLUDE
    ]

    for direction in ("bearish", "bullish"):
        gates: list[Gate] = [NO_GATE]
        dir_df = group_df[group_df["direction"] == direction]
        if dir_df.empty:
            result[direction] = gates
            continue

        for col in num_cols:
            series = dir_df[col].dropna()
            if len(series) < 20:
                continue

            col_min, col_max = float(series.min()), float(series.max())
            if col_max == col_min:
                continue

            # Determine threshold precision
            if col in _ORDINAL_INT or (series.dtype.kind in ("i", "u")):
                # Integer ordinals — use integer values directly
                vals_set: set[float] = set()
                for q in (0.25, 0.50, 0.75):
                    v = float(np.round(series.quantile(q)))
                    vals_set.add(v)
                thresholds = sorted(vals_set)
            else:
                # Continuous — round to 2 dp
                vals_set = set()
                for q in (0.25, 0.50, 0.75):
                    v = round(float(series.quantile(q)), 2)
                    vals_set.add(v)
                thresholds = sorted(vals_set)

            for thresh in thresholds:
                if thresh <= col_min or thresh >= col_max:
                    continue
                gates.append(_num_gate(col, ">=", thresh))
                gates.append(_num_gate(col, "<=", thresh))

        # Categorical: aoi_classification, session_directional_bias
        for cat_col in _CATEGORICAL:
            if cat_col not in dir_df.columns:
                continue
            for val in dir_df[cat_col].dropna().unique():
                gates.append(_cat_gate(cat_col, str(val)))

        # conflicted_tf — null check
        if "conflicted_tf" in dir_df.columns:
            gates.append(_null_gate("conflicted_tf"))
            gates.append(_notnull_gate("conflicted_tf"))

        result[direction] = gates
        logger.info(
            "    Gate candidates [%s, %s]: %d", direction, "group", len(gates)
        )

    return result


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
    df: pd.DataFrame, span_years: float, min_tpy: float
) -> Optional[dict]:
    if len(df) < 10 or span_years < 0.01:
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
        "tpy": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gp / max(gl, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    return df[df["rr_multiple"] == RR_VALUE].copy()


# ---------------------------------------------------------------------------
# Phase 1: fast screen — best (SL, window) per group
# ---------------------------------------------------------------------------


def phase1_screen(
    group_name: str,
    symbols: list[str],
    df: pd.DataFrame,
    sl_models: list[str],
    windows: dict[str, list[int]],
    span_years: float,
) -> list[dict]:
    """
    Sweep all SL models × all windows for this group.
    Returns rows sorted by win_pct DESC (no gate applied).
    """
    group_df = df[df["symbol"].isin(symbols)]
    rows: list[dict] = []
    for sl in sl_models:
        sl_df = group_df[group_df["sl_model"] == sl]
        if sl_df.empty:
            continue
        for win_name, hours in windows.items():
            sub = sl_df[sl_df["hour_of_day_utc"].isin(hours)]
            m = compute_metrics(sub, span_years, MIN_TPY_PHASE1)
            if m and m["expectancy_r"] > 0:
                rows.append({"sl_model": sl, "window": win_name,
                             "hours": hours, **m})
    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase 2: directional gate search
# ---------------------------------------------------------------------------


def phase2_directional(
    candidate: dict,
    group_df: pd.DataFrame,
    dir_gates: dict[str, list[Gate]],
    span_years: float,
    sl_models: list[str],
    group_df_all: pd.DataFrame,
    symbols: list[str],
) -> Optional[dict]:
    """
    For one (SL, window) candidate:
      2a. Find best single gate for bearish subset.
      2b. Find best single gate for bullish subset.
      2c. Try top-K bear × top-K bull combinations → pick best combined.
      2d. Try different SL per direction with the best gates.
    Returns the best config dict, or None if no viable combination.
    """
    sl = candidate["sl_model"]
    hours = candidate["hours"]

    base = group_df[
        (group_df["sl_model"] == sl)
        & group_df["hour_of_day_utc"].isin(hours)
    ]
    if base.empty:
        return None

    bear_base = base[base["direction"] == "bearish"]
    bull_base = base[base["direction"] == "bullish"]

    # ------------------------------------------------------------------
    # 2a/2b: per-direction gate sweep
    # ------------------------------------------------------------------
    def _sweep_dir(dir_df: pd.DataFrame, gate_list: list[Gate]) -> list[dict]:
        rows: list[dict] = []
        for label, fn in gate_list:
            try:
                filtered = fn(dir_df)
                m = compute_metrics(filtered, span_years, MIN_TPY_DIR)
                if m:
                    rows.append({"gate_label": label, "gate_fn": fn, **m})
            except Exception:  # noqa: BLE001
                pass
        return sorted(rows, key=lambda r: r["win_pct"], reverse=True)

    bear_results = _sweep_dir(bear_base, dir_gates.get("bearish", [NO_GATE]))
    bull_results = _sweep_dir(bull_base, dir_gates.get("bullish", [NO_GATE]))

    if not bear_results or not bull_results:
        return None

    # ------------------------------------------------------------------
    # 2c: combine top-K bear × top-K bull
    # ------------------------------------------------------------------
    best_combined: Optional[dict] = None

    top_bear = bear_results[:TOP_DIR_GATES]
    top_bull = bull_results[:TOP_DIR_GATES]

    for b_row in top_bear:
        for u_row in top_bull:
            try:
                bear_filtered = b_row["gate_fn"](bear_base)
                bull_filtered = u_row["gate_fn"](bull_base)
                combined = pd.concat([bear_filtered, bull_filtered], ignore_index=True)
                m = compute_metrics(combined, span_years, MIN_TPY_COMBINED)
                if m is None:
                    continue
                candidate_cfg = {
                    "bear_gate": b_row["gate_label"],
                    "bull_gate": u_row["gate_label"],
                    "bear_win_pct": b_row["win_pct"],
                    "bear_tpy": b_row["tpy"],
                    "bull_win_pct": u_row["win_pct"],
                    "bull_tpy": u_row["tpy"],
                    "bear_sl": sl,
                    "bull_sl": sl,
                    **m,
                }
                if best_combined is None or m["win_pct"] > best_combined["win_pct"]:
                    best_combined = candidate_cfg
            except Exception:  # noqa: BLE001
                pass

    if best_combined is None:
        return None

    # ------------------------------------------------------------------
    # 2d: try different SL per direction using best bear/bull gates
    # ------------------------------------------------------------------
    best_bear_fn = next(
        (r["gate_fn"] for r in bear_results if r["gate_label"] == best_combined["bear_gate"]),
        NO_GATE[1],
    )
    best_bull_fn = next(
        (r["gate_fn"] for r in bull_results if r["gate_label"] == best_combined["bull_gate"]),
        NO_GATE[1],
    )

    for bear_sl in sl_models:
        for bull_sl in sl_models:
            if bear_sl == sl and bull_sl == sl:
                continue  # already tested
            try:
                bear_sl_df = group_df_all[
                    group_df_all["symbol"].isin(symbols)
                    & group_df_all["sl_model"].eq(bear_sl)
                    & group_df_all["hour_of_day_utc"].isin(hours)
                    & (group_df_all["direction"] == "bearish")
                ]
                bull_sl_df = group_df_all[
                    group_df_all["symbol"].isin(symbols)
                    & group_df_all["sl_model"].eq(bull_sl)
                    & group_df_all["hour_of_day_utc"].isin(hours)
                    & (group_df_all["direction"] == "bullish")
                ]
                bear_filt = best_bear_fn(bear_sl_df)
                bull_filt = best_bull_fn(bull_sl_df)
                combined = pd.concat([bear_filt, bull_filt], ignore_index=True)
                m = compute_metrics(combined, span_years, MIN_TPY_COMBINED)
                if m and m["win_pct"] > best_combined["win_pct"]:
                    best_combined = {
                        **best_combined,
                        "bear_sl": bear_sl,
                        "bull_sl": bull_sl,
                        **m,
                    }
            except Exception:  # noqa: BLE001
                pass

    return best_combined


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    sl_models = sorted(df["sl_model"].dropna().unique())
    windows = generate_windows()

    logger.info(
        "Dataset: %.2f years | %d rows | %d SL models | %d windows",
        span_years, len(df), len(sl_models), len(windows),
    )
    logger.info("SL models: %s", sl_models)

    breakdown_rows: list[dict] = []
    group_portfolio_parts: list[pd.DataFrame] = []

    for group_name, symbols in EXCLUSIVE_GROUPS.items():
        logger.info("=" * 70)
        logger.info("GROUP: %s  [%s]", group_name, ", ".join(symbols))

        group_df_all = df[df["symbol"].isin(symbols)].copy()
        if group_df_all.empty:
            logger.info("  No data for group.")
            continue

        # ---------------------------------------------------------------
        # Phase 1: screen all SL × window
        # ---------------------------------------------------------------
        logger.info("  Phase 1: screening %d SL × %d windows...",
                    len(sl_models), len(windows))
        p1_rows = phase1_screen(
            group_name, symbols, df, sl_models, windows, span_years
        )
        if not p1_rows:
            logger.info("  Phase 1: no viable (SL, window) found.")
            continue

        # Deduplicate to top-N unique (SL, window) combos
        seen_combos: set[tuple[str, str]] = set()
        top_candidates: list[dict] = []
        for row in p1_rows:
            key = (row["sl_model"], row["window"])
            if key not in seen_combos:
                seen_combos.add(key)
                top_candidates.append(row)
            if len(top_candidates) >= TOP_SL_CANDIDATES * TOP_WINDOWS_PER_SL:
                break

        logger.info("  Phase 1 top candidates:")
        for c in top_candidates[:9]:
            logger.info(
                "    SL=%-26s win=%.4f tpy=%6.1f exp=%.4f  window=%s",
                c["sl_model"], c["win_pct"], c["tpy"],
                c["expectancy_r"], c["window"],
            )

        # ---------------------------------------------------------------
        # Build direction-specific gate library (from full group data)
        # ---------------------------------------------------------------
        logger.info("  Building directional gate library...")
        dir_gates = build_dir_gate_library(group_df_all)

        # ---------------------------------------------------------------
        # Phase 2: directional gate search on each candidate
        # ---------------------------------------------------------------
        logger.info("  Phase 2: directional gate search on top %d candidates...",
                    len(top_candidates))
        phase2_best: Optional[dict] = None

        for cand in top_candidates:
            group_win_df = group_df_all[group_df_all["sl_model"] == cand["sl_model"]]
            result = phase2_directional(
                cand, group_win_df, dir_gates, span_years,
                sl_models, group_df_all, symbols,
            )
            if result is None:
                continue
            if phase2_best is None or result["win_pct"] > phase2_best["win_pct"]:
                phase2_best = {
                    "main_sl": cand["sl_model"],
                    "window": cand["window"],
                    "window_hours": str(cand["hours"]),
                    "p1_win_pct": cand["win_pct"],
                    "p1_tpy": cand["tpy"],
                    **result,
                }

        if phase2_best is None:
            logger.info("  Phase 2: no viable directional config found.")
            # Fall back to best Phase 1 result (no directional gate)
            best_p1 = top_candidates[0]
            logger.info(
                "  Fallback to Phase 1 best: SL=%s win=%.4f tpy=%.1f window=%s",
                best_p1["sl_model"], best_p1["win_pct"],
                best_p1["tpy"], best_p1["window"],
            )
            breakdown_rows.append({
                "group": group_name, "symbols": str(sorted(symbols)),
                "phase": "fallback_p1",
                "main_sl": best_p1["sl_model"], "bear_sl": best_p1["sl_model"],
                "bull_sl": best_p1["sl_model"],
                "window": best_p1["window"], "window_hours": str(best_p1["hours"]),
                "bear_gate": "no_gate", "bull_gate": "no_gate",
                "p1_win_pct": best_p1["win_pct"], "p1_tpy": best_p1["tpy"],
                **{k: best_p1.get(k) for k in
                   ("win_pct", "tpy", "expectancy_r", "max_losing_streak", "profit_factor")},
            })
            # Add to portfolio using best Phase 1 config
            sl_b = best_p1["sl_model"]
            hrs_b = best_p1["hours"]
            part = group_df_all[
                (group_df_all["sl_model"] == sl_b)
                & group_df_all["hour_of_day_utc"].isin(hrs_b)
            ].copy()
            part["_group"] = group_name
            group_portfolio_parts.append(part)
            continue

        logger.info(
            "  Phase 2 best: SL=%s/%s window=%s  win=%.4f tpy=%.1f exp=%.4f mls=%d",
            phase2_best["bear_sl"], phase2_best["bull_sl"],
            phase2_best["window"], phase2_best["win_pct"],
            phase2_best["tpy"], phase2_best["expectancy_r"],
            phase2_best["max_losing_streak"],
        )
        logger.info(
            "  Bear gate: %s  (bear_win=%.4f, bear_tpy=%.1f)",
            phase2_best["bear_gate"], phase2_best["bear_win_pct"],
            phase2_best["bear_tpy"],
        )
        logger.info(
            "  Bull gate: %s  (bull_win=%.4f, bull_tpy=%.1f)",
            phase2_best["bull_gate"], phase2_best["bull_win_pct"],
            phase2_best["bull_tpy"],
        )

        breakdown_rows.append({
            "group": group_name,
            "symbols": str(sorted(symbols)),
            "phase": "directional",
            **{k: phase2_best.get(k) for k in (
                "main_sl", "bear_sl", "bull_sl", "window", "window_hours",
                "bear_gate", "bull_gate",
                "p1_win_pct", "p1_tpy",
                "bear_win_pct", "bear_tpy", "bull_win_pct", "bull_tpy",
                "win_pct", "tpy", "expectancy_r", "max_losing_streak",
                "profit_factor", "n_trades",
            )},
        })

        # Reconstruct the portfolio slice for this group
        bear_sl = phase2_best["bear_sl"]
        bull_sl = phase2_best["bull_sl"]
        hours = eval(phase2_best["window_hours"])

        # Rebuild the directional gate functions from labels
        bear_label = phase2_best["bear_gate"]
        bull_label = phase2_best["bull_gate"]

        # Find the actual gate functions from the library
        def _find_fn(label: str, gate_list: list[Gate]) -> GateFn:
            for gl, gfn in gate_list:
                if gl == label:
                    return gfn
            return NO_GATE[1]

        bear_fn = _find_fn(bear_label, dir_gates.get("bearish", [NO_GATE]))
        bull_fn = _find_fn(bull_label, dir_gates.get("bullish", [NO_GATE]))

        bear_part = group_df_all[
            (group_df_all["sl_model"] == bear_sl)
            & (group_df_all["direction"] == "bearish")
            & group_df_all["hour_of_day_utc"].isin(hours)
        ]
        bull_part = group_df_all[
            (group_df_all["sl_model"] == bull_sl)
            & (group_df_all["direction"] == "bullish")
            & group_df_all["hour_of_day_utc"].isin(hours)
        ]
        bear_filtered = bear_fn(bear_part)
        bull_filtered = bull_fn(bull_part)
        group_slice = pd.concat([bear_filtered, bull_filtered], ignore_index=True)
        group_slice["_group"] = group_name
        group_portfolio_parts.append(group_slice)

    # -----------------------------------------------------------------------
    # Phase 3: combined portfolio
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("PHASE 3 — Combined portfolio (%d groups)", len(group_portfolio_parts))

    if not group_portfolio_parts:
        logger.error("No group slices built — cannot form portfolio.")
        return

    portfolio = pd.concat(group_portfolio_parts, ignore_index=True)
    # Dedup: (entry_signal_id, sl_model) is a unique trade
    portfolio = portfolio.drop_duplicates(subset=["entry_signal_id", "sl_model"]).copy()

    m_port = compute_metrics(portfolio, span_years, 1.0)
    if m_port:
        logger.info(
            "Combined portfolio: win=%.4f tpy=%.1f exp=%.4f mls=%d pf=%.3f  (%d trades)",
            m_port["win_pct"], m_port["tpy"], m_port["expectancy_r"],
            m_port["max_losing_streak"], m_port["profit_factor"], m_port["n_trades"],
        )

    # Per-group contribution
    for group_name in EXCLUSIVE_GROUPS:
        part = portfolio[portfolio["_group"] == group_name]
        if part.empty:
            continue
        m_g = compute_metrics(part, span_years, 1.0)
        if m_g:
            logger.info(
                "  %-14s: win=%.4f tpy=%6.1f exp=%.4f mls=%d",
                group_name, m_g["win_pct"], m_g["tpy"],
                m_g["expectancy_r"], m_g["max_losing_streak"],
            )

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------
    if breakdown_rows:
        bd = pd.DataFrame(breakdown_rows)
        bd.to_csv(BREAKDOWN_PATH, index=False)
        logger.info("Saved breakdown → %s", BREAKDOWN_PATH)

    result_record = {
        "n_groups": len(group_portfolio_parts),
        "groups": "+".join(
            g for g in EXCLUSIVE_GROUPS if any(
                p["_group"].eq(g).any() if "_group" in p.columns else False
                for p in group_portfolio_parts
            )
        ),
        **(m_port or {}),
    }
    pd.DataFrame([result_record]).to_csv(RESULTS_PATH, index=False)
    logger.info("Saved results → %s", RESULTS_PATH)


if __name__ == "__main__":
    main()
