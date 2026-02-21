#!/usr/bin/env python3
"""
Group portfolio builder.

For each logical pair group, discovers its optimal contiguous trading window
independently, then combines viable groups into a single unified portfolio
and sweeps gate combinations on top.

Anti-overfitting rules:
  - Windows fitted at GROUP level (not per symbol)
  - Groups defined by fundamental currency relationships (not backtest ranking)
  - Min GROUP_MIN_TPY=50 per group for window discovery
  - Min GROUP_MIN_WIN=0.365 to include a group in the portfolio
  - Gate depth <= 2, clean round thresholds only
  - Overlapping symbols across groups handled by deduplication (entry_signal_id)

Output: analysis/group_portfolio_results.csv

Usage:
    cd data-retriever
    python group_portfolio_builder.py
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

GROUP_MIN_TPY: float = 50.0       # per-group floor for window discovery
GROUP_MIN_WIN: float = 0.365      # min win_pct for group to enter portfolio
GROUP_MIN_EXP: float = 0.0        # min expectancy_r for group to enter portfolio
PORTFOLIO_MIN_TPY: float = 100.0  # combined portfolio must meet this
MIN_TRADES_ABS: int = 20          # absolute floor per group evaluation

RR_VALUE: float = 2.0

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "group_portfolio_results.csv"

# ---------------------------------------------------------------------------
# Logical pair groups  (fundamental — not backtest-derived)
# ---------------------------------------------------------------------------

PAIR_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors": ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "gbp_pairs":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "EURGBP"],
    "eur_pairs":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "aud_bloc":   ["AUDCAD", "AUDCHF", "AUDJPY", "AUDUSD", "EURAUD", "GBPAUD"],
    "nzd_bloc":   ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD", "EURNZD", "GBPNZD"],
    "high_vol":   ["GBPJPY", "EURJPY", "GBPAUD", "GBPNZD", "EURAUD", "EURNZD"],
    "cad_pairs":  ["AUDCAD", "EURCAD", "GBPCAD", "NZDCAD", "USDCAD", "CADJPY"],
    "chf_pairs":  ["AUDCHF", "EURCHF", "GBPCHF", "NZDCHF", "USDCHF", "CHFJPY"],
    "commodity":  ["AUDCAD", "AUDNZD", "NZDCAD", "AUDCHF", "NZDCHF", "CADJPY", "NZDJPY"],
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
# Gate library (identical to mega_simulation — clean round thresholds)
# ---------------------------------------------------------------------------

GateFn = Callable[[pd.DataFrame], pd.DataFrame]
Gate = tuple[str, GateFn]


def _col_filter(df: pd.DataFrame, col: str, op: str, val: float) -> pd.DataFrame:
    if col not in df.columns:
        return df
    return df[df[col] <= val] if op == "<=" else df[df[col] >= val]


def sg(col: str, op: str, val: float) -> Gate:
    return (
        f"{col}{op}{val}",
        lambda df, c=col, o=op, v=val: _col_filter(df, c, o, v),
    )


def g2(g_a: Gate, g_b: Gate) -> Gate:
    la, fa = g_a
    lb, fb = g_b
    return f"{la} & {lb}", lambda df: fb(fa(df))


def htf_plain(threshold: float) -> Gate:
    label = f"htf_range_mid>={threshold}"
    def fn(df: pd.DataFrame, _t: float = threshold) -> pd.DataFrame:
        col = "htf_range_position_mid"
        return df[df[col] >= _t] if col in df.columns else df
    return label, fn


def htf_dir(threshold: float) -> Gate:
    label = f"htf_dir>={threshold}"
    def fn(df: pd.DataFrame, _t: float = threshold) -> pd.DataFrame:
        col, dcol = "htf_range_position_mid", "direction"
        if col not in df.columns or dcol not in df.columns:
            return df
        mask = (
            ((df[dcol] == "bearish") & (df[col] >= _t))
            | ((df[dcol] == "bullish") & (df[col] <= (1.0 - _t)))
        )
        return df[mask]
    return label, fn


def htf_bear_bull(bear_thresh: float, bull_thresh: float) -> Gate:
    label = f"bear_htf>={bear_thresh}&bull_htf>={bull_thresh}"
    def fn(df: pd.DataFrame, _bt: float = bear_thresh, _blt: float = bull_thresh) -> pd.DataFrame:
        col, dcol = "htf_range_position_mid", "direction"
        if col not in df.columns or dcol not in df.columns:
            return df
        mask = (
            ((df[dcol] == "bearish") & (df[col] >= _bt))
            | ((df[dcol] == "bullish") & (df[col] >= _blt))
        )
        return df[mask]
    return label, fn


_BARS   = "bars_between_retest_and_break"
_DIST   = "distance_to_next_htf_obstacle_atr"
_BCL    = "break_close_location"
_SCO    = "signal_candle_opposite_extreme_atr"
_MRP    = "max_retest_penetration_atr"
_AOI_F  = "aoi_far_edge_atr"
_AOI_N  = "aoi_near_edge_atr"
_TREND  = "trend_age_impulses"
_HTF_SZ = "htf_range_size_mid_atr"
_DIST_I = "distance_from_last_impulse_atr"

SINGLE_GATES: list[Gate] = [
    sg(_BARS,  "<=", 1), sg(_BARS,  "<=", 2), sg(_BARS,  "<=", 3), sg(_BARS,  "<=", 4),
    sg(_DIST,  ">=", 0.25), sg(_DIST,  ">=", 0.5), sg(_DIST,  ">=", 0.75), sg(_DIST,  ">=", 1.0),
    sg(_BCL,   ">=", 0.5),  sg(_BCL,   ">=", 0.65), sg(_BCL,   ">=", 0.7),  sg(_BCL,   ">=", 0.75),
    sg(_SCO,   ">=", 0.25), sg(_SCO,   ">=", 0.35), sg(_SCO,   ">=", 0.5),
    sg(_MRP,   "<=", 0.5),  sg(_MRP,   "<=", 1.0),  sg(_MRP,   "<=", 1.25), sg(_MRP,   "<=", 1.5),
    sg(_AOI_F, ">=", 1.0),  sg(_AOI_F, ">=", 1.5),  sg(_AOI_F, ">=", 2.0),
    sg(_AOI_N, ">=", 0.25), sg(_AOI_N, ">=", 0.5),  sg(_AOI_N, ">=", 1.0),
    sg(_TREND, ">=", 3),    sg(_TREND, ">=", 5),
    sg(_HTF_SZ,">=", 10),   sg(_HTF_SZ,">=", 15),   sg(_HTF_SZ,">=", 20),
    sg(_DIST_I,">=", 0.5),  sg(_DIST_I,">=", 1.0),  sg(_DIST_I,">=", 1.5),
    htf_plain(0.4),  htf_plain(0.5),
    htf_dir(0.4),    htf_dir(0.45),   htf_dir(0.5),
    htf_bear_bull(0.4, 0.3), htf_bear_bull(0.7, 0.3),
]

TWO_GATE_COMBOS: list[Gate] = [
    g2(sg(_BARS, "<=", 2), sg(_DIST,  ">=", 0.25)),
    g2(sg(_BARS, "<=", 2), sg(_BCL,   ">=", 0.65)),
    g2(sg(_BARS, "<=", 2), sg(_SCO,   ">=", 0.35)),
    g2(sg(_BARS, "<=", 2), sg(_MRP,   "<=", 1.25)),
    g2(sg(_BARS, "<=", 2), sg(_AOI_F, ">=", 1.5)),
    g2(sg(_BARS, "<=", 2), sg(_BCL,   ">=", 0.5)),
    g2(sg(_BARS, "<=", 2), sg(_AOI_N, ">=", 0.25)),
    g2(sg(_BARS, "<=", 2), sg(_HTF_SZ,">=", 10)),
    g2(sg(_BARS, "<=", 3), sg(_DIST,  ">=", 0.25)),
    g2(sg(_BARS, "<=", 3), sg(_BCL,   ">=", 0.65)),
    g2(sg(_BARS, "<=", 3), sg(_DIST,  ">=", 0.5)),
    g2(sg(_BARS, "<=", 3), sg(_MRP,   "<=", 1.25)),
    g2(sg(_DIST, ">=", 0.25), sg(_BCL,   ">=", 0.65)),
    g2(sg(_DIST, ">=", 0.5),  sg(_BCL,   ">=", 0.65)),
    g2(sg(_DIST, ">=", 0.25), sg(_MRP,   "<=", 1.25)),
    g2(sg(_DIST, ">=", 0.25), sg(_SCO,   ">=", 0.35)),
    g2(sg(_DIST, ">=", 0.25), sg(_AOI_N, ">=", 0.25)),
    g2(sg(_BCL,  ">=", 0.65), sg(_MRP,   "<=", 1.25)),
    g2(sg(_BCL,  ">=", 0.5),  sg(_DIST,  ">=", 0.25)),
    g2(sg(_BCL,  ">=", 0.7),  sg(_MRP,   "<=", 1.25)),
    g2(sg(_AOI_F,">=", 1.5),  sg(_DIST,  ">=", 0.25)),
    g2(sg(_AOI_F,">=", 1.5),  sg(_BARS,  "<=", 3)),
    g2(sg(_MRP,  "<=", 1.0),  sg(_SCO,   ">=", 0.5)),
    g2(sg(_MRP,  "<=", 1.25), sg(_SCO,   ">=", 0.35)),
    g2(sg(_DIST, ">=", 0.5),  sg(_BARS,  "<=", 3)),
    g2(htf_dir(0.4), sg(_BARS, "<=", 3)),
    g2(htf_dir(0.4), sg(_BARS, "<=", 2)),
    g2(htf_plain(0.4), sg(_BCL,  ">=", 0.65)),
    g2(htf_plain(0.4), sg(_DIST, ">=", 0.25)),
    g2(htf_bear_bull(0.8, 0.3), sg(_BARS, "<=", 3)),
]

NO_GATE: Gate = ("no_gate", lambda df: df)
ALL_GATES: list[Gate] = [NO_GATE] + SINGLE_GATES + TWO_GATE_COMBOS

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
# Per-group window discovery
# ---------------------------------------------------------------------------


def find_best_window(
    group_df: pd.DataFrame,
    windows: dict[str, list[int]],
    span_years: float,
) -> Optional[tuple[str, list[int], dict]]:
    """
    Find best window for a group by win_pct.
    Returns (window_name, hours, metrics) or None.
    """
    best: Optional[tuple[str, list[int], dict]] = None
    for win_name, hours in windows.items():
        filtered = group_df[group_df["hour_of_day_utc"].isin(hours)]
        m = compute_metrics(filtered, span_years, GROUP_MIN_TPY)
        if m is None:
            continue
        if best is None or m["win_pct"] > best[2]["win_pct"]:
            best = (win_name, hours, m)
    return best


# ---------------------------------------------------------------------------
# Combined portfolio
# ---------------------------------------------------------------------------


def build_combined_portfolio(
    assignments: list[tuple[str, list[int]]],
    base_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Union of (group_symbols × window) slices, deduplicated by entry_signal_id.
    Handles symbol overlap across groups cleanly.
    """
    parts: list[pd.DataFrame] = []
    for symbols, hours in assignments:
        mask = base_df["symbol"].isin(symbols) & base_df["hour_of_day_utc"].isin(hours)
        parts.append(base_df[mask])
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)
    return combined.drop_duplicates(subset=["entry_signal_id"]).copy()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years, %d rows, RR=%.1f", span_years, len(df), RR_VALUE)

    windows = generate_windows()
    logger.info("Windows: %d", len(windows))
    logger.info("Gates: %d", len(ALL_GATES))

    sl_models = sorted(df["sl_model"].dropna().unique())
    logger.info("SL models: %s", sl_models)

    all_results: list[dict] = []

    for sl_model in sl_models:
        base_df = df[df["sl_model"] == sl_model].copy()
        if base_df.empty:
            continue

        # ATR1 seed quality gate
        if sl_model == "SL_ATR_1_0" and "break_close_location" in base_df.columns:
            base_df = base_df[base_df["break_close_location"] <= 0.921].copy()

        logger.info("[%s] %d rows after seed filter", sl_model, len(base_df))

        # ---------------------------------------------------------------
        # Step 1: find best window per group
        # ---------------------------------------------------------------
        group_assignments: list[tuple[str, list[int]]] = []   # (symbols, hours)
        group_summary: list[dict] = []

        for group_name, symbols in PAIR_GROUPS.items():
            group_df = base_df[base_df["symbol"].isin(symbols)]
            if group_df.empty:
                continue
            result = find_best_window(group_df, windows, span_years)
            if result is None:
                logger.info("  [%s] %s — no viable window", sl_model, group_name)
                continue
            win_name, hours, m = result
            status = "INCLUDE" if m["win_pct"] >= GROUP_MIN_WIN and m["expectancy_r"] > GROUP_MIN_EXP else "EXCLUDE"
            logger.info(
                "  [%s] %s | best_window=%s  win=%.4f  tpy=%.1f  exp=%.4f  mls=%d  → %s",
                sl_model, group_name, win_name,
                m["win_pct"], m["trades_per_year"], m["expectancy_r"],
                m["max_losing_streak"], status,
            )
            group_summary.append({
                "sl_model": sl_model,
                "group": group_name,
                "best_window": win_name,
                "best_window_hours": str(hours),
                "status": status,
                **{f"group_{k}": v for k, v in m.items()},
            })
            if status == "INCLUDE":
                group_assignments.append((symbols, hours))

        if not group_assignments:
            logger.info("[%s] no viable groups — skipping portfolio build", sl_model)
            continue

        n_groups = len(group_assignments)
        logger.info("[%s] building portfolio from %d groups", sl_model, n_groups)

        # ---------------------------------------------------------------
        # Step 2: combined portfolio — gate sweep
        # ---------------------------------------------------------------
        portfolio_df = build_combined_portfolio(group_assignments, base_df)
        logger.info("[%s] combined portfolio: %d unique trades", sl_model, len(portfolio_df))

        for gate_label, gate_fn in ALL_GATES:
            try:
                gated = gate_fn(portfolio_df)
                m = compute_metrics(gated, span_years, PORTFOLIO_MIN_TPY)
                if m is None:
                    continue
                all_results.append({
                    "sl_model": sl_model,
                    "n_groups": n_groups,
                    "gate_label": gate_label,
                    **m,
                })
            except Exception:  # noqa: BLE001
                pass

    if not all_results:
        logger.error("No results produced.")
        return

    result_df = (
        pd.DataFrame(all_results)
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )
    result_df.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(result_df), OUT_PATH)

    # Print top 20 by win_pct
    top20 = result_df.head(20)
    cols = ["sl_model", "n_groups", "gate_label", "win_pct",
            "expectancy_r", "trades_per_year", "max_losing_streak", "profit_factor"]
    avail = [c for c in cols if c in top20.columns]
    logger.info("=== TOP 20 BY WIN PCT ===\n%s", top20[avail].to_string(index=False))

    # Top 10 by lowest streak (win >= 0.38)
    streak_top = (
        result_df[result_df["win_pct"] >= 0.38]
        .sort_values("max_losing_streak")
        .head(10)
    )
    if not streak_top.empty:
        logger.info("=== TOP 10 LOWEST STREAK (win>=38%%) ===\n%s",
                    streak_top[avail].to_string(index=False))

    # Best per SL model
    for sl in result_df["sl_model"].unique():
        best = result_df[result_df["sl_model"] == sl].iloc[0]
        logger.info(
            "Best [%s]: win=%.4f  tpy=%.1f  exp=%.4f  mls=%d  gate=%s",
            sl, best["win_pct"], best["trades_per_year"],
            best["expectancy_r"], best["max_losing_streak"], best["gate_label"],
        )


if __name__ == "__main__":
    main()
