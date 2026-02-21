#!/usr/bin/env python3
"""
Mega simulation: exhaustive search across SL models × RR × pair groups × windows × gates.

Combines all gate candidates from prior analysis into one comprehensive sweep.

Design rules:
  - Pairs:   named logical groups only (jpy_pairs, gbp_pairs, etc.) — NO individual picking
  - Windows: ALL contiguous blocks of 3-10 hours from every starting hour (h00+3h … h23+10h)
             plus standard named sessions for interpretability
  - Gates:   all clean thresholds (round numbers) from prior analysis, depth 1 and 2
  - RR:      2.0, 2.5, 3.0
  - SL:      all models found in data (SL_ATR_1_0, SL_SIGNAL_CANDLE, SL_AOI_FAR, …)
  - Floor:   >= 100 tpy, >= 50 total trades, expectancy_r > 0

Output: analysis/mega_simulation_results.csv  (full results)
        top-10 logged by win_pct DESC / max_losing_streak ASC

Usage:
    cd data-retriever
    python mega_simulation.py
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

MIN_TPY: int = 100
MIN_TRADES_ABS: int = 50
TOP_N: int = 10
RR_VALUES: list[float] = [2.0, 2.5, 3.0]

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "mega_simulation_results.csv"

# ---------------------------------------------------------------------------
# Pair groups  (logical, named — no cherry-picked individual pairs)
# ---------------------------------------------------------------------------

PAIR_GROUPS: dict[str, Optional[list[str]]] = {
    "all":        None,
    "jpy_pairs":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors": ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "gbp_pairs":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "EURGBP"],
    "eur_pairs":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "aud_bloc":   ["AUDCAD", "AUDCHF", "AUDJPY", "AUDUSD", "EURAUD", "GBPAUD"],
    "nzd_bloc":   ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD", "EURNZD", "GBPNZD"],
    "high_vol":   ["GBPJPY", "EURJPY", "GBPAUD", "GBPNZD", "EURAUD", "EURNZD"],
}

# ---------------------------------------------------------------------------
# Window generation  (all contiguous blocks — no cherry-picked hours)
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
    """All contiguous forward blocks (3-10h from every start) + named sessions."""
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

GateSpec = tuple[str, str, float]
GateFn = Callable[[pd.DataFrame], pd.DataFrame]
Gate = tuple[str, GateFn]


def _col_filter(df: pd.DataFrame, col: str, op: str, val: float) -> pd.DataFrame:
    if col not in df.columns:
        return df
    return df[df[col] <= val] if op == "<=" else df[df[col] >= val]


def sg(col: str, op: str, val: float) -> Gate:
    """Simple clean threshold gate."""
    return (
        f"{col}{op}{val}",
        lambda df, c=col, o=op, v=val: _col_filter(df, c, o, v),
    )


def g2(g_a: Gate, g_b: Gate) -> Gate:
    """AND-combine two gates (depth-2)."""
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
    """Directional HTF gate: bearish >= t OR bullish <= (1-t)."""
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
    """Direction-split: bearish uses bear_thresh (>=), bullish uses bull_thresh (>=)."""
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


# ---------------------------------------------------------------------------
# Gate library
# ---------------------------------------------------------------------------

# All clean single gates from prior analysis
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
    # Retest speed — single most impactful gate
    sg(_BARS,  "<=", 1), sg(_BARS,  "<=", 2), sg(_BARS,  "<=", 3), sg(_BARS,  "<=", 4),
    # Distance to next HTF obstacle (room to run)
    sg(_DIST,  ">=", 0.25), sg(_DIST,  ">=", 0.5), sg(_DIST,  ">=", 0.75), sg(_DIST,  ">=", 1.0),
    # Break candle close quality
    sg(_BCL,   ">=", 0.5),  sg(_BCL,   ">=", 0.65), sg(_BCL,   ">=", 0.7),  sg(_BCL,   ">=", 0.75),
    # Signal candle size (ATR-normalised opposite extreme)
    sg(_SCO,   ">=", 0.25), sg(_SCO,   ">=", 0.35), sg(_SCO,   ">=", 0.5),
    # Retest penetration depth (shallow retest = clean entry)
    sg(_MRP,   "<=", 0.5),  sg(_MRP,   "<=", 1.0),  sg(_MRP,   "<=", 1.25), sg(_MRP,   "<=", 1.5),
    # AOI far edge distance (structural depth)
    sg(_AOI_F, ">=", 1.0),  sg(_AOI_F, ">=", 1.5),  sg(_AOI_F, ">=", 2.0),
    # AOI near edge (entry quality)
    sg(_AOI_N, ">=", 0.25), sg(_AOI_N, ">=", 0.5),  sg(_AOI_N, ">=", 1.0),
    # Trend maturity
    sg(_TREND, ">=", 3),    sg(_TREND, ">=", 5),
    # HTF range size (trade in mature ranges only)
    sg(_HTF_SZ,">=", 10),   sg(_HTF_SZ,">=", 15),   sg(_HTF_SZ,">=", 20),
    # Distance from last impulse (fresh vs stale setups)
    sg(_DIST_I,">=", 0.5),  sg(_DIST_I,">=", 1.0),  sg(_DIST_I,">=", 1.5),
    # HTF range position (plain and directional)
    htf_plain(0.4),  htf_plain(0.5),
    htf_dir(0.4),    htf_dir(0.45),   htf_dir(0.5),
    htf_bear_bull(0.4, 0.3), htf_bear_bull(0.7, 0.3),
]

# Pre-defined depth-2 combos (proven from prior analysis)
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
    df = df[df["rr_multiple"].isin(RR_VALUES)].copy()
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
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years, %d rows", span_years, len(df))

    windows = generate_windows()
    logger.info("Windows: %d", len(windows))
    logger.info("Gates:   %d", len(ALL_GATES))
    logger.info("Groups:  %d", len(PAIR_GROUPS))

    # Discover available (sl_model, rr) combos
    seed_combos = (
        df[["sl_model", "rr_multiple"]]
        .drop_duplicates()
        .sort_values(["sl_model", "rr_multiple"])
    )
    logger.info("Seed combos available:\n%s", seed_combos.to_string(index=False))

    n_total = len(seed_combos) * len(PAIR_GROUPS) * len(windows) * len(ALL_GATES)
    logger.info("Upper bound evaluations: %d", n_total)

    all_rows: list[dict] = []
    n_done = 0
    n_recorded = 0

    for _, seed_row in seed_combos.iterrows():
        sl_model: str = seed_row["sl_model"]
        rr: float = seed_row["rr_multiple"]

        base_df = df[(df["sl_model"] == sl_model) & (df["rr_multiple"] == rr)]
        if len(base_df) < MIN_TRADES_ABS:
            continue

        logger.info("[%s / RR=%.1f] %d rows", sl_model, rr, len(base_df))

        for group_name, group_symbols in PAIR_GROUPS.items():
            if group_symbols is not None:
                group_df = base_df[base_df["symbol"].isin(group_symbols)]
            else:
                group_df = base_df

            if len(group_df) < MIN_TRADES_ABS:
                continue

            for win_label, win_hours in windows.items():
                win_df = group_df[group_df["hour_of_day_utc"].isin(win_hours)]

                if len(win_df) < MIN_TRADES_ABS:
                    n_done += len(ALL_GATES)
                    continue

                for gate_label, gate_fn in ALL_GATES:
                    gated = gate_fn(win_df)
                    m = compute_metrics(gated, span_years)
                    if m is not None:
                        all_rows.append({
                            "sl_model":   sl_model,
                            "rr":         rr,
                            "group":      group_name,
                            "window":     win_label,
                            "gate":       gate_label,
                            "n_gate_terms": 0 if gate_label == "no_gate"
                                          else gate_label.count(" & ") + 1,
                            **m,
                        })
                        n_recorded += 1
                    n_done += 1

                if n_done % 100_000 == 0:
                    logger.info(
                        "  progress: %d evals done, %d recorded",
                        n_done, n_recorded,
                    )

    if not all_rows:
        logger.warning("No results passed the floor — check data / thresholds")
        return

    results = pd.DataFrame(all_rows).sort_values(
        ["win_pct", "max_losing_streak"],
        ascending=[False, True],
    )
    results.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(results), OUT_PATH)

    # ── Report ───────────────────────────────────────────────────────────────
    display_cols = [
        "sl_model", "rr", "group", "window", "gate",
        "trades_per_year", "win_pct", "expectancy_r",
        "max_losing_streak", "profit_factor", "n_trades",
    ]
    avail = [c for c in display_cols if c in results.columns]

    logger.info("=== TOP %d BY WIN%% (primary) / MAX LOSING STREAK (secondary) ===", TOP_N)
    logger.info("\n%s", results[avail].head(TOP_N).to_string(index=False))

    logger.info("=== TOP %d BY LOWEST MAX LOSING STREAK (win%% >= 0.40) ===", TOP_N)
    quality = results[results["win_pct"] >= 0.40].sort_values(
        ["max_losing_streak", "win_pct"], ascending=[True, False]
    )
    logger.info("\n%s", quality[avail].head(TOP_N).to_string(index=False))

    logger.info("=== TOP %d BY EXPECTANCY_R ===", TOP_N)
    logger.info(
        "\n%s",
        results.sort_values("expectancy_r", ascending=False)[avail]
        .head(TOP_N).to_string(index=False),
    )

    # Per SL model / RR breakdown
    for (sl, rr_val), grp in results.groupby(["sl_model", "rr"]):
        logger.info("=== TOP 5 — %s / RR=%.1f ===", sl, rr_val)
        logger.info("\n%s", grp[avail].head(5).to_string(index=False))

    logger.info("Total passing configs: %d", len(results))
    logger.info("Unique seeds: %s",
                results[["sl_model", "rr"]].drop_duplicates().to_string(index=False))


if __name__ == "__main__":
    main()
