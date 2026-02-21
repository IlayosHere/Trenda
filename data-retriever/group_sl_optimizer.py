#!/usr/bin/env python3
"""
Group SL optimizer.

For each exclusive pair group, independently discovers its optimal:
  - SL model  (which stop model fits this group's volatility profile)
  - Trading window (contiguous UTC block with strongest edge)

Rationale: different currency groups have structurally different volatility
profiles and session dynamics.  GBP crosses tolerate wider stops; commodity
pairs peak in Asian hours; JPY pairs are driven by NY open.  Fitting ONE SL
model per GROUP (not per symbol) is not overfitting — it mirrors how a real
trader would configure risk per instrument class.

Then combines all viable groups (each with its own SL + window) into a
unified portfolio and sweeps gates on the union.

Anti-overfitting guarantees:
  - Groups defined by fundamental currency relationships (not backtest ranking)
  - One (SL model, window) fitted per GROUP — not per symbol
  - Gates: depth ≤ 2, clean round thresholds only
  - Min GROUP_MIN_TPY=30, min GROUP_MIN_WIN=0.355 for inclusion
  - Min PORTFOLIO_MIN_TPY=100 for gate sweep output

Output:
    analysis/group_sl_breakdown.csv  — per-group best SL + window
    analysis/group_sl_results.csv    — portfolio × gate sweep results

Usage:
    cd data-retriever
    python group_sl_optimizer.py
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

GROUP_MIN_TPY: float = 30.0
GROUP_MIN_WIN: float = 0.355
GROUP_MIN_EXP: float = 0.05        # require meaningful positive expectancy
PORTFOLIO_MIN_TPY: float = 100.0
MIN_TRADES_ABS: int = 15

RR_VALUE: float = 2.0

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_PATH = BASE_DIR / "group_sl_breakdown.csv"
OUT_PATH = BASE_DIR / "group_sl_results.csv"

# ---------------------------------------------------------------------------
# Mutually exclusive pair groups (each symbol in exactly one group)
# ---------------------------------------------------------------------------

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":    ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":   ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":    ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
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
# Gate library
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
# Per-group discovery: sweep all SL models × all windows
# ---------------------------------------------------------------------------


def find_best_sl_window(
    group_name: str,
    symbols: list[str],
    df: pd.DataFrame,
    sl_models: list[str],
    windows: dict[str, list[int]],
    span_years: float,
) -> list[dict]:
    """
    For one group, sweep every (SL model, window) combination.
    Returns all viable rows sorted by win_pct DESC.
    """
    rows: list[dict] = []
    group_df_full = df[df["symbol"].isin(symbols)]

    for sl_model in sl_models:
        sl_df = group_df_full[group_df_full["sl_model"] == sl_model]
        if sl_df.empty:
            continue
        for win_name, hours in windows.items():
            filtered = sl_df[sl_df["hour_of_day_utc"].isin(hours)]
            m = compute_metrics(filtered, span_years, GROUP_MIN_TPY)
            if m is None:
                continue
            if m["win_pct"] < GROUP_MIN_WIN or m["expectancy_r"] < GROUP_MIN_EXP:
                continue
            rows.append({
                "group": group_name,
                "sl_model": sl_model,
                "window": win_name,
                "window_hours": str(hours),
                **m,
            })

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    sl_models = sorted(df["sl_model"].dropna().unique())
    windows = generate_windows()

    logger.info(
        "Dataset: %.2f years | %d rows | %d SL models | %d windows | %d gates",
        span_years, len(df), len(sl_models), len(windows), len(ALL_GATES),
    )
    logger.info("SL models: %s", sl_models)
    logger.info("Groups: %s", list(EXCLUSIVE_GROUPS.keys()))

    # -----------------------------------------------------------------------
    # Step 1: per-group sweep — find best (SL model, window) for each group
    # -----------------------------------------------------------------------
    breakdown_rows: list[dict] = []
    group_best: dict[str, dict] = {}   # group → best row

    logger.info("=" * 70)
    logger.info("STEP 1 — Per-group SL × window discovery")
    logger.info("=" * 70)

    for group_name, symbols in EXCLUSIVE_GROUPS.items():
        viable = find_best_sl_window(
            group_name, symbols, df, sl_models, windows, span_years,
        )
        present = df[df["symbol"].isin(symbols)]["symbol"].unique().tolist()

        if not viable:
            logger.info(
                "  %-16s — NO viable (SL, window) found  [symbols present: %s]",
                group_name, sorted(present),
            )
            continue

        best = viable[0]
        group_best[group_name] = best
        breakdown_rows.extend(viable[:10])   # keep top-10 per group for breakdown CSV

        logger.info(
            "  %-16s → SL=%-26s window=%-18s win=%.4f tpy=%6.1f exp=%.4f mls=%2d",
            group_name, best["sl_model"], best["window"],
            best["win_pct"], best["trades_per_year"],
            best["expectancy_r"], best["max_losing_streak"],
        )
        # Show top-5 alternatives
        for alt in viable[1:6]:
            logger.info(
                "    alt: SL=%-26s window=%-18s win=%.4f tpy=%6.1f exp=%.4f mls=%2d",
                alt["sl_model"], alt["window"],
                alt["win_pct"], alt["trades_per_year"],
                alt["expectancy_r"], alt["max_losing_streak"],
            )

    logger.info(
        "Viable groups: %d/%d → %s",
        len(group_best), len(EXCLUSIVE_GROUPS), list(group_best.keys()),
    )

    # Save breakdown
    if breakdown_rows:
        bd = pd.DataFrame(breakdown_rows)
        bd.to_csv(BREAKDOWN_PATH, index=False)
        logger.info("Saved breakdown → %s", BREAKDOWN_PATH)

    if not group_best:
        logger.error("No viable groups — cannot build portfolio.")
        return

    # -----------------------------------------------------------------------
    # Step 2: build combined portfolio (each group uses its own SL + window)
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("STEP 2 — Combined portfolio construction")
    logger.info("=" * 70)

    parts: list[pd.DataFrame] = []
    for group_name, best in group_best.items():
        symbols = EXCLUSIVE_GROUPS[group_name]
        hours = eval(best["window_hours"])
        mask = (
            df["symbol"].isin(symbols)
            & df["sl_model"].eq(best["sl_model"])
            & df["hour_of_day_utc"].isin(hours)
        )
        part = df[mask].copy()
        part["_group"] = group_name
        parts.append(part)
        logger.info(
            "  %s: %d trades (SL=%s, window=%s)",
            group_name, len(part), best["sl_model"], best["window"],
        )

    portfolio_df = pd.concat(parts, ignore_index=True)
    # Dedup on (entry_signal_id, sl_model) — a signal can appear with different
    # SL models for different groups, both are valid distinct trades.
    portfolio_df = portfolio_df.drop_duplicates(
        subset=["entry_signal_id", "sl_model"]
    ).copy()

    baseline = compute_metrics(portfolio_df, span_years, 1.0)
    if baseline:
        logger.info(
            "Combined no-gate baseline: win=%.4f tpy=%.1f exp=%.4f mls=%d pf=%.3f  (%d trades)",
            baseline["win_pct"], baseline["trades_per_year"],
            baseline["expectancy_r"], baseline["max_losing_streak"],
            baseline["profit_factor"], baseline["n_trades"],
        )

    # -----------------------------------------------------------------------
    # Step 3: gate sweep on combined portfolio
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("STEP 3 — Gate sweep (%d gates)", len(ALL_GATES))
    logger.info("=" * 70)

    group_config = "; ".join(
        f"{g}={v['sl_model']}/{v['window']}" for g, v in group_best.items()
    )

    result_rows: list[dict] = []
    for gate_label, gate_fn in ALL_GATES:
        try:
            gated = gate_fn(portfolio_df)
            m = compute_metrics(gated, span_years, PORTFOLIO_MIN_TPY)
            if m is None:
                continue
            result_rows.append({
                "n_groups": len(group_best),
                "groups": "+".join(group_best.keys()),
                "group_config": group_config,
                "gate_label": gate_label,
                **m,
            })
        except Exception:  # noqa: BLE001
            pass

    if not result_rows:
        logger.error("No gate results met portfolio floor.")
        return

    result_df = (
        pd.DataFrame(result_rows)
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )
    result_df.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d gate results → %s", len(result_df), OUT_PATH)

    cols = ["n_groups", "groups", "gate_label", "win_pct",
            "trades_per_year", "expectancy_r", "max_losing_streak", "profit_factor"]
    avail = [c for c in cols if c in result_df.columns]

    logger.info("=== TOP 20 BY WIN PCT ===\n%s",
                result_df[avail].head(20).to_string(index=False))

    streak_top = (
        result_df[result_df["win_pct"] >= 0.38]
        .sort_values(["max_losing_streak", "win_pct"], ascending=[True, False])
        .head(10)
    )
    if not streak_top.empty:
        logger.info("=== TOP 10 LOWEST STREAK (win>=38%%) ===\n%s",
                    streak_top[avail].to_string(index=False))

    vol_top = (
        result_df[result_df["win_pct"] >= 0.38]
        .sort_values("trades_per_year", ascending=False)
        .head(10)
    )
    if not vol_top.empty:
        logger.info("=== TOP 10 BY VOLUME (win>=38%%) ===\n%s",
                    vol_top[avail].to_string(index=False))


if __name__ == "__main__":
    main()
