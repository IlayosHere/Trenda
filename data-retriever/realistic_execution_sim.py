#!/usr/bin/env python3
"""
realistic_execution_sim.py

Apply real execution constraints to the top configurations:
  1. Same-symbol cooldown: no trading the same symbol within 3 hours of a prior entry
  2. Max concurrent trades: never hold more than 4 trades simultaneously

Uses exit_bar (H1 bars to trade close) to track when trades actually end.
Processes signals chronologically and drops any that violate constraints.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
COOLDOWN_HOURS: int = 3
MAX_CONCURRENT: int = 4

BASE_DIR = Path(__file__).parent
ANALYSIS_DIR = BASE_DIR / "analysis"
SIGNALS_CSV = ANALYSIS_DIR / "signals.csv"
EXIT_SIM_CSV = ANALYSIS_DIR / "exit_simulations.csv"
TUNED_CSV = ANALYSIS_DIR / "tuned_window_configs.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

# Per-group MILD bull gates
MILD_BULL = {
    "jpy_pairs":   ("signal_candle_opposite_extreme_atr", "<=", 0.7),
    "usd_majors":  ("session_directional_bias", ">=", 0.2),
    "eur_crosses": ("aoi_height_atr", "<=", 1.3),
    "gbp_crosses": ("session_directional_bias", ">=", 0.1),
}

# Per-group TIGHT bull gates
TIGHT_BULL = {
    "jpy_pairs":   ("signal_candle_opposite_extreme_atr", "<=", 0.7),
    "usd_majors":  ("session_directional_bias", ">=", 0.2),
    "eur_crosses": ("aoi_height_atr", "<=", 1.3),
    "gbp_crosses": ("session_directional_bias", ">=", 0.1),
    "commodity":   ("distance_from_last_impulse_atr", "<=", 0.38),
}


def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"] == RR].copy()
    df["htf_zone"] = "mid"
    df.loc[df["htf_range_position_mid"] >= PREMIUM_THRESHOLD, "htf_zone"] = "premium"
    df.loc[df["htf_range_position_mid"] <= DISCOUNT_THRESHOLD, "htf_zone"] = "discount"
    sym_to_grp = {}
    for grp, syms in EXCLUSIVE_GROUPS.items():
        for s in syms:
            sym_to_grp[s] = grp
    df["group"] = df["symbol"].map(sym_to_grp)
    df = df[df["group"].notna()].copy()
    # Compute exit_time from signal_time + exit_bar hours
    df["exit_time"] = df["signal_time"] + pd.to_timedelta(df["exit_bar"].fillna(48), unit="h")
    return df


def _mls(exits: list[str]) -> int:
    s = mx = 0
    for e in exits:
        if e == "SL":
            s += 1; mx = max(mx, s)
        elif e == "TP":
            s = 0
    return mx


def met(df: pd.DataFrame, sy: float, min_n: int = 10) -> Optional[dict]:
    if len(df) < min_n or sy < 0.01:
        return None
    tpy = len(df) / sy
    ds = df.sort_values("signal_time")
    exp = float(ds["return_r"].mean())
    gp = ds.loc[ds["return_r"] > 0, "return_r"].sum()
    gl = abs(ds.loc[ds["return_r"] < 0, "return_r"].sum())
    return {
        "n": len(ds), "tpy": round(tpy, 1),
        "win": round(float((ds["exit_reason"] == "TP").mean()) * 100, 2),
        "exp": round(exp, 4),
        "mls": _mls(ds["exit_reason"].tolist()),
        "pf": round(gp / max(gl, 1e-9), 3),
    }


def apply_gate(df: pd.DataFrame, col: str, op: str, thresh: float) -> pd.DataFrame:
    if op == ">=":
        return df[df[col] >= thresh]
    return df[df[col] <= thresh]


# ---------------------------------------------------------------------------
# Execution simulation
# ---------------------------------------------------------------------------
def simulate_execution(portfolio: pd.DataFrame) -> pd.DataFrame:
    """
    Walk through signals chronologically and apply:
      1. Same-symbol 3h cooldown
      2. Max 4 concurrent trades
    Returns the subset of trades that would actually be taken.
    """
    sorted_df = portfolio.sort_values("signal_time").reset_index(drop=True)

    taken_indices = []
    # Track: {symbol: last_entry_time}
    symbol_last_entry: dict[str, pd.Timestamp] = {}
    # Track open trades: list of (exit_time,)
    open_trades: list[pd.Timestamp] = []

    cooldown_td = pd.Timedelta(hours=COOLDOWN_HOURS)

    for idx, row in sorted_df.iterrows():
        entry_time = row["signal_time"]
        symbol = row["symbol"]
        exit_time = row["exit_time"]

        # Clean up expired trades
        open_trades = [et for et in open_trades if et > entry_time]

        # Check 1: Same-symbol cooldown
        if symbol in symbol_last_entry:
            if entry_time - symbol_last_entry[symbol] < cooldown_td:
                continue  # Skip — too soon for this symbol

        # Check 2: Max concurrent trades
        if len(open_trades) >= MAX_CONCURRENT:
            continue  # Skip — too many open trades

        # Trade is taken
        taken_indices.append(idx)
        symbol_last_entry[symbol] = entry_time
        open_trades.append(exit_time)

    return sorted_df.loc[taken_indices].copy()


# ---------------------------------------------------------------------------
# Portfolio builders
# ---------------------------------------------------------------------------
def build_portfolio(
    df: pd.DataFrame,
    bull_gates: Optional[dict] = None,
    excl_hours: Optional[set[int]] = None,
) -> pd.DataFrame:
    """Build full portfolio from tuned configs with optional bull gates and hour exclusion."""
    bear = df[(df["direction"] == "bearish") & (df["aoi_touch_count_since_creation"] <= 3)]
    bull = df[(df["direction"] == "bullish") & (df["session_directional_bias"] >= 0.0)]

    configs = pd.read_csv(TUNED_CSV)
    parts = []
    for _, cfg in configs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        direction = cfg["direction"]
        grp = cfg["group"]
        source = bear if direction == "bearish" else bull

        sub = source[
            (source["group"] == grp) &
            (source["htf_zone"] == cfg["zone"]) &
            (source["sl_model"] == cfg["sl_model"]) &
            (source["hour_of_day_utc"].isin(hours))
        ]

        # Apply per-group bull gate
        if direction == "bullish" and bull_gates and grp in bull_gates:
            col, op, thresh = bull_gates[grp]
            sub = apply_gate(sub, col, op, thresh)

        if len(sub) >= 5:
            parts.append(sub)

    pf = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    # Apply global hour exclusion
    if excl_hours and not pf.empty:
        pf = pf[~pf["hour_of_day_utc"].isin(excl_hours)]

    return pf


# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", sy, len(df))

    # Check exit_bar distribution
    rr_df = df[df["rr_multiple"] == RR]
    logger.info(
        "Exit bar stats (hours to close): mean=%.1f  median=%.1f  p75=%.1f  p95=%.1f  max=%.0f",
        rr_df["exit_bar"].mean(), rr_df["exit_bar"].median(),
        rr_df["exit_bar"].quantile(0.75), rr_df["exit_bar"].quantile(0.95),
        rr_df["exit_bar"].max(),
    )

    # Build all configs
    excl_17_20 = {17, 18, 19}
    excl_12_14 = {12, 13}

    configs = [
        ("#1 MILD bull + excl_h17+3h", MILD_BULL, excl_17_20),
        ("#2 Baseline + excl_h17+3h", None, excl_17_20),
        ("#3 MILD bull + excl_h12+2h", MILD_BULL, excl_12_14),
        ("#4 TIGHT bull (no excl)", TIGHT_BULL, None),
        ("#5 MILD bull (no excl)", MILD_BULL, None),
        ("#6 Baseline (no excl)", None, None),
    ]

    logger.info("\n" + "=" * 120)
    logger.info("BEFORE vs AFTER execution constraints")
    logger.info("(cooldown=%dh same-symbol, max %d concurrent)", COOLDOWN_HOURS, MAX_CONCURRENT)
    logger.info("=" * 120)

    results = []
    for label, bull_gates, excl in configs:
        pf = build_portfolio(df, bull_gates, excl)
        before = met(pf, sy, 5)

        # Simulate execution
        executed = simulate_execution(pf)
        after = met(executed, sy, 5)

        if before and after:
            dropped = before["n"] - after["n"]
            drop_pct = round(dropped / before["n"] * 100, 1)

            logger.info("\n  %s:", label)
            logger.info(
                "    BEFORE: n=%4d  tpy=%5.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f",
                before["n"], before["tpy"], before["win"], before["exp"], before["mls"], before["pf"],
            )
            logger.info(
                "    AFTER:  n=%4d  tpy=%5.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f",
                after["n"], after["tpy"], after["win"], after["exp"], after["mls"], after["pf"],
            )
            logger.info(
                "    DROPPED: %d trades (%.1f%%)", dropped, drop_pct,
            )

            # Per-direction breakdown after
            for d in ["bearish", "bullish"]:
                dm = met(executed[executed["direction"] == d], sy, 5)
                if dm:
                    logger.info(
                        "      %-10s  n=%4d  tpy=%5.1f  win=%5.2f%%  mls=%2d",
                        d, dm["n"], dm["tpy"], dm["win"], dm["mls"],
                    )

            results.append({
                "config": label,
                "before_n": before["n"], "before_tpy": before["tpy"], "before_win": before["win"],
                "after_n": after["n"], "after_tpy": after["tpy"], "after_win": after["win"],
                "after_exp": after["exp"], "after_mls": after["mls"], "after_pf": after["pf"],
                "dropped": dropped, "drop_pct": drop_pct,
                "score": round(after["exp"] / max(after["mls"], 1), 4),
            })

    # Summary table sorted by score
    logger.info("\n" + "=" * 120)
    logger.info("FINAL RANKING (after execution constraints, scored by exp/MLS)")
    logger.info("=" * 120)
    rdf = pd.DataFrame(results).sort_values("score", ascending=False)
    disp = ["config", "before_n", "before_tpy", "after_n", "after_tpy", "after_win",
            "after_exp", "after_mls", "after_pf", "drop_pct", "score"]
    logger.info("\n%s", rdf[disp].to_string(index=False))

    # ===============================================================
    # YoY for all configs AFTER constraints
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("YEAR-OVER-YEAR (after constraints)")
    logger.info("=" * 120)

    for label, bull_gates, excl in configs:
        pf = build_portfolio(df, bull_gates, excl)
        executed = simulate_execution(pf)
        executed_sorted = executed.sort_values("signal_time")
        executed_sorted["year"] = executed_sorted["signal_time"].dt.year

        logger.info("\n  %s:", label)
        for year in sorted(executed_sorted["year"].unique()):
            ydf = executed_sorted[executed_sorted["year"] == year]
            ym = met(ydf, 1.0, 5)
            if ym:
                logger.info(
                    "    %d: n=%3d  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f",
                    year, ym["n"], ym["win"], ym["exp"], ym["mls"], ym["pf"],
                )

    # ===============================================================
    # Concurrent trade stats
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("CONCURRENT TRADE STATS (baseline config)")
    logger.info("=" * 120)

    pf = build_portfolio(df, None, None)
    executed = simulate_execution(pf)
    sorted_ex = executed.sort_values("signal_time")

    # Count max concurrent at each entry
    max_conc = 0
    avg_conc_list = []
    open_trades: list[pd.Timestamp] = []
    for _, row in sorted_ex.iterrows():
        open_trades = [et for et in open_trades if et > row["signal_time"]]
        open_trades.append(row["exit_time"])
        avg_conc_list.append(len(open_trades))
        max_conc = max(max_conc, len(open_trades))

    logger.info(
        "  Max concurrent (after filter): %d  |  Avg concurrent: %.1f",
        max_conc, sum(avg_conc_list) / max(len(avg_conc_list), 1),
    )

    logger.info("\nDONE")


if __name__ == "__main__":
    main()
