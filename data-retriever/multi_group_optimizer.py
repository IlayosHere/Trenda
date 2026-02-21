#!/usr/bin/env python3
"""
Multi-group portfolio optimizer.

Uses mutually exclusive pair groups — each symbol belongs to exactly one group.
No deduplication needed, so combined portfolio tpy is fully additive.

Each group independently discovers its optimal contiguous window.
Viable groups are combined and the full gate library is swept on the union.

Key improvements over group_portfolio_builder.py:
  - Exclusive (non-overlapping) group definitions → additive volume
  - Lower GROUP_MIN_WIN=0.36 to include more groups
  - Lower GROUP_MIN_TPY=30 per group
  - Per-group breakdown saved to CSV for full transparency
  - Greedy addition mode: adds groups only while combined quality stays above floor

Output:
    analysis/multi_group_breakdown.csv — per-group window selection details
    analysis/multi_group_results.csv   — portfolio × gate sweep results

Usage:
    cd data-retriever
    python multi_group_optimizer.py
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

GROUP_MIN_TPY: float = 30.0       # per-group floor for window discovery
GROUP_MIN_WIN: float = 0.360      # min win_pct for group to be a candidate
GROUP_MIN_EXP: float = 0.0        # min expectancy_r for group candidacy
GREEDY_WIN_FLOOR: float = 0.375   # combined portfolio must stay above this in greedy mode
GREEDY_MIN_UNIQUE_TPY: float = 8.0  # group must contribute at least this many unique tpy
PORTFOLIO_MIN_TPY: float = 100.0  # final portfolio floor for gate sweep
MIN_TRADES_ABS: int = 15

RR_VALUE: float = 2.0

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_PATH = BASE_DIR / "multi_group_breakdown.csv"
OUT_PATH = BASE_DIR / "multi_group_results.csv"

# ---------------------------------------------------------------------------
# Mutually exclusive pair groups
# Each symbol belongs to exactly one group.
# Priority: JPY > USD > EUR > GBP > commodity
# ---------------------------------------------------------------------------

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    # All JPY crosses — most liquid, most volatile, natural cluster
    "jpy_pairs": [
        "AUDJPY", "CADJPY", "CHFJPY", "EURJPY",
        "GBPJPY", "NZDJPY", "USDJPY",
    ],
    # USD vs major non-JPY currencies
    "usd_majors": [
        "AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF",
    ],
    # EUR crosses (non-JPY, non-USD)
    "eur_crosses": [
        "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD",
    ],
    # GBP crosses (non-JPY, non-USD, non-EUR)
    "gbp_crosses": [
        "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    ],
    # Commodity currency crosses (AUD/NZD vs CAD/CHF, no major)
    "commodity": [
        "AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF",
    ],
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
# Gate library (same clean round thresholds throughout all scripts)
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
    min_tpy: float = GROUP_MIN_TPY,
) -> Optional[tuple[str, list[int], dict]]:
    best: Optional[tuple[str, list[int], dict]] = None
    for win_name, hours in windows.items():
        filtered = group_df[group_df["hour_of_day_utc"].isin(hours)]
        m = compute_metrics(filtered, span_years, min_tpy)
        if m is None:
            continue
        if best is None or m["win_pct"] > best[2]["win_pct"]:
            best = (win_name, hours, m)
    return best


# ---------------------------------------------------------------------------
# Portfolio build + gate sweep
# ---------------------------------------------------------------------------


def build_portfolio(
    assignments: list[tuple[str, list[int]]],
    base_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Union of (symbols × window) slices.
    Exclusive groups: no deduplication needed.
    Kept for safety in case groups are switched to overlapping.
    """
    parts: list[pd.DataFrame] = []
    for symbols, hours in assignments:
        mask = base_df["symbol"].isin(symbols) & base_df["hour_of_day_utc"].isin(hours)
        parts.append(base_df[mask])
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)
    return combined.drop_duplicates(subset=["entry_signal_id"]).copy()


def sweep_gates(
    portfolio_df: pd.DataFrame,
    span_years: float,
    sl_model: str,
    mode: str,
    n_groups: int,
    group_names: str,
) -> list[dict]:
    rows: list[dict] = []
    for gate_label, gate_fn in ALL_GATES:
        try:
            gated = gate_fn(portfolio_df)
            m = compute_metrics(gated, span_years, PORTFOLIO_MIN_TPY)
            if m is None:
                continue
            rows.append({
                "sl_model": sl_model,
                "mode": mode,
                "n_groups": n_groups,
                "groups": group_names,
                "gate_label": gate_label,
                **m,
            })
        except Exception:  # noqa: BLE001
            pass
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years, %d rows, RR=%.1f", span_years, len(df), RR_VALUE)

    windows = generate_windows()
    logger.info("Windows: %d | Gates: %d", len(windows), len(ALL_GATES))

    sl_models = sorted(df["sl_model"].dropna().unique())
    logger.info("SL models: %s", sl_models)

    breakdown_rows: list[dict] = []
    result_rows: list[dict] = []

    for sl_model in sl_models:
        base_df = df[df["sl_model"] == sl_model].copy()
        if base_df.empty:
            continue

        logger.info("=" * 60)
        logger.info("[%s] %d rows", sl_model, len(base_df))

        # -------------------------------------------------------------------
        # Per-group window discovery
        # -------------------------------------------------------------------
        group_results: list[dict] = []   # full info per group

        for group_name, symbols in EXCLUSIVE_GROUPS.items():
            group_df = base_df[base_df["symbol"].isin(symbols)]
            present = group_df["symbol"].unique().tolist()
            if group_df.empty:
                logger.info("  %s — no data", group_name)
                continue

            result = find_best_window(group_df, windows, span_years)
            if result is None:
                logger.info("  %s — no viable window (symbols present: %s)", group_name, present)
                continue

            win_name, hours, m = result
            viable = m["win_pct"] >= GROUP_MIN_WIN and m["expectancy_r"] > GROUP_MIN_EXP
            logger.info(
                "  %-16s | window=%-18s win=%.4f tpy=%6.1f exp=%.4f mls=%2d  %s",
                group_name, win_name,
                m["win_pct"], m["trades_per_year"],
                m["expectancy_r"], m["max_losing_streak"],
                "INCLUDE" if viable else "EXCLUDE",
            )
            group_results.append({
                "sl_model": sl_model,
                "group": group_name,
                "symbols": str(sorted(present)),
                "best_window": win_name,
                "best_window_hours": str(hours),
                "viable": viable,
                **{f"grp_{k}": v for k, v in m.items()},
            })
            breakdown_rows.append(group_results[-1])

        viable_groups = [g for g in group_results if g["viable"]]
        logger.info("[%s] %d/%d groups viable", sl_model, len(viable_groups), len(group_results))

        if not viable_groups:
            continue

        # -------------------------------------------------------------------
        # Mode A: threshold-based — all viable groups combined
        # -------------------------------------------------------------------
        assignments_a = [
            (EXCLUSIVE_GROUPS[g["group"]], eval(g["best_window_hours"]))
            for g in viable_groups
        ]
        portfolio_a = build_portfolio(assignments_a, base_df)
        base_m_a = compute_metrics(portfolio_a, span_years, 1.0)
        group_names_a = "+".join(g["group"] for g in viable_groups)
        if base_m_a:
            logger.info(
                "[%s] Mode A (%s): no_gate → win=%.4f tpy=%.1f exp=%.4f mls=%d",
                sl_model, group_names_a,
                base_m_a["win_pct"], base_m_a["trades_per_year"],
                base_m_a["expectancy_r"], base_m_a["max_losing_streak"],
            )
        result_rows.extend(sweep_gates(
            portfolio_a, span_years, sl_model, "threshold",
            len(viable_groups), group_names_a,
        ))

        # -------------------------------------------------------------------
        # Mode B: greedy — add groups while combined quality stays >= floor
        # -------------------------------------------------------------------
        # Sort candidates by standalone win_pct descending
        candidates = sorted(viable_groups, key=lambda g: g["grp_win_pct"], reverse=True)
        greedy_assignments: list[tuple[list[str], list[int]]] = []
        greedy_df = pd.DataFrame()
        greedy_groups: list[str] = []

        for g in candidates:
            symbols = EXCLUSIVE_GROUPS[g["group"]]
            hours = eval(g["best_window_hours"])
            # Tentative addition
            mask = base_df["symbol"].isin(symbols) & base_df["hour_of_day_utc"].isin(hours)
            new_trades = base_df[mask]
            tentative = pd.concat(
                [greedy_df, new_trades], ignore_index=True
            ).drop_duplicates(subset=["entry_signal_id"])

            m_tent = compute_metrics(tentative, span_years, 1.0)
            if m_tent is None:
                continue

            # Check: quality floor maintained
            if m_tent["win_pct"] < GREEDY_WIN_FLOOR:
                logger.info(
                    "  Greedy skip %s: combined win=%.4f < floor %.3f",
                    g["group"], m_tent["win_pct"], GREEDY_WIN_FLOOR,
                )
                continue

            # Check: meaningful unique contribution
            current_tpy = len(greedy_df) / span_years if not greedy_df.empty else 0
            new_tpy = m_tent["trades_per_year"] - current_tpy
            if greedy_df.empty or new_tpy >= GREEDY_MIN_UNIQUE_TPY:
                greedy_df = tentative
                greedy_groups.append(g["group"])
                greedy_assignments.append((symbols, hours))
                logger.info(
                    "  Greedy ADD %s: combined win=%.4f tpy=%.1f (+%.1f unique/yr)",
                    g["group"], m_tent["win_pct"], m_tent["trades_per_year"], new_tpy,
                )
            else:
                logger.info(
                    "  Greedy skip %s: only %.1f unique tpy added (min %.1f)",
                    g["group"], new_tpy, GREEDY_MIN_UNIQUE_TPY,
                )

        if greedy_groups and len(greedy_groups) != len(viable_groups):
            group_names_b = "+".join(greedy_groups)
            base_m_b = compute_metrics(greedy_df, span_years, 1.0)
            if base_m_b:
                logger.info(
                    "[%s] Mode B (%s): no_gate → win=%.4f tpy=%.1f exp=%.4f mls=%d",
                    sl_model, group_names_b,
                    base_m_b["win_pct"], base_m_b["trades_per_year"],
                    base_m_b["expectancy_r"], base_m_b["max_losing_streak"],
                )
            result_rows.extend(sweep_gates(
                greedy_df, span_years, sl_model, "greedy",
                len(greedy_groups), group_names_b,
            ))

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------
    if breakdown_rows:
        bd = pd.DataFrame(breakdown_rows).sort_values(["sl_model", "group"])
        bd.to_csv(BREAKDOWN_PATH, index=False)
        logger.info("Saved breakdown → %s (%d rows)", BREAKDOWN_PATH, len(bd))

    if not result_rows:
        logger.error("No results produced.")
        return

    result_df = (
        pd.DataFrame(result_rows)
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )
    result_df.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d result rows → %s", len(result_df), OUT_PATH)

    # Summary
    top20 = result_df.head(20)
    cols = ["sl_model", "mode", "n_groups", "groups", "gate_label",
            "win_pct", "trades_per_year", "expectancy_r", "max_losing_streak", "profit_factor"]
    avail = [c for c in cols if c in top20.columns]
    logger.info("=== TOP 20 BY WIN PCT ===\n%s", top20[avail].to_string(index=False))

    # Top 10 lowest streak, win >= 38%
    streak_top = (
        result_df[result_df["win_pct"] >= 0.38]
        .sort_values(["max_losing_streak", "win_pct"], ascending=[True, False])
        .head(10)
    )
    if not streak_top.empty:
        logger.info("=== TOP 10 LOWEST STREAK (win>=38%%) ===\n%s",
                    streak_top[avail].to_string(index=False))

    # Best by volume (win >= 39%, tpy-sorted)
    vol_top = (
        result_df[result_df["win_pct"] >= 0.39]
        .sort_values("trades_per_year", ascending=False)
        .head(10)
    )
    if not vol_top.empty:
        logger.info("=== TOP 10 BY VOLUME (win>=39%%) ===\n%s",
                    vol_top[avail].to_string(index=False))

    # Best per sl_model
    for sl in result_df["sl_model"].unique():
        best = result_df[result_df["sl_model"] == sl].iloc[0]
        logger.info(
            "Best [%s]: win=%.4f tpy=%.1f exp=%.4f mls=%d mode=%s gate=%s",
            sl, best["win_pct"], best["trades_per_year"],
            best["expectancy_r"], best["max_losing_streak"],
            best["mode"], best["gate_label"],
        )


if __name__ == "__main__":
    main()
