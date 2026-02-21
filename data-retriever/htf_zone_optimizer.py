#!/usr/bin/env python3
"""
HTF zone optimizer.

Hypothesis: direction × HTF position zone is the primary edge discriminator.
  - Bearish at PREMIUM (htf_range_position_mid >= 0.75) → sell into resistance
  - Bullish at DISCOUNT (htf_range_position_mid <= 0.25) → buy into support
  - Mid-zone trades are structural noise

Per group × direction × zone:
  - Sweep all 11 SL models × all contiguous windows
  - Record viable configs (win_pct >= MIN_WIN_BUCKET, tpy >= MIN_TPY_BUCKET)

Combine best viable bucket configs into unified portfolio, sweep single gates.

Anti-overfitting guarantees:
  - Groups defined by fundamental currency relationships
  - One (SL model, window) per GROUP × DIRECTION × ZONE bucket
  - Zone thresholds fixed at 0.75 / 0.25 (round, not data-derived)
  - Min 20 tpy per bucket, min 80 tpy for portfolio gate output

Output:
    analysis/htf_zone_breakdown.csv  — per-bucket best configs
    analysis/htf_zone_results.csv    — portfolio gate sweep

Usage:
    cd data-retriever
    python htf_zone_optimizer.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
RR: float = 2.0

MIN_TPY_BUCKET: float = 20.0
MIN_WIN_BUCKET: float = 0.355
MIN_EXP_BUCKET: float = 0.05
MIN_TRADES_ABS: int = 15

MIN_TPY_PORTFOLIO: float = 80.0

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_OUT = BASE_DIR / "htf_zone_breakdown.csv"
RESULTS_OUT = BASE_DIR / "htf_zone_results.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

ALL_SL_MODELS: list[str] = [
    "SL_AOI_FAR", "SL_AOI_FAR_PLUS_0_25",
    "SL_AOI_NEAR", "SL_AOI_NEAR_PLUS_0_25", "SL_AOI_NEAR_PLUS_0_5",
    "SL_ATR_0_5", "SL_ATR_1_0", "SL_ATR_1_5", "SL_ATR_2_0",
    "SL_SIGNAL_CANDLE", "SL_SIGNAL_CANDLE_PLUS_0_25",
]

# Columns excluded from gate sweep
_EXCLUDE_GATE: set[str] = {
    "id", "entry_signal_id", "signal_time", "symbol", "direction",
    "sl_model", "rr_multiple", "sl_atr", "exit_reason", "return_r",
    "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "hour_of_day_utc", "htf_zone",
    "htf_range_position_mid", "htf_range_position_high",
    "_bucket",
}


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------

def _gen_windows() -> list[tuple[str, list[int]]]:
    return [
        (f"h{s:02d}+{l}h", [(s + i) % 24 for i in range(l)])
        for s in range(24) for l in range(2, 13)
    ]


ALL_WINDOWS: list[tuple[str, list[int]]] = _gen_windows()


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
# Bucket sweep
# ---------------------------------------------------------------------------

def sweep_bucket(
    bucket_df: pd.DataFrame,
    span_years: float,
) -> list[dict]:
    """Sweep all SL × window combos for one group×direction×zone bucket."""
    rows: list[dict] = []
    for sl in ALL_SL_MODELS:
        sl_df = bucket_df[bucket_df["sl_model"] == sl]
        if len(sl_df) < MIN_TRADES_ABS:
            continue
        for win_name, hours in ALL_WINDOWS:
            win_df = sl_df[sl_df["hour_of_day_utc"].isin(hours)]
            m = compute_metrics(win_df, span_years, MIN_TPY_BUCKET)
            if m and m["win_pct"] >= MIN_WIN_BUCKET and m["expectancy_r"] >= MIN_EXP_BUCKET:
                rows.append({
                    "sl_model": sl,
                    "window": win_name,
                    "window_hours": hours,
                    **m,
                })
    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Portfolio gate sweep
# ---------------------------------------------------------------------------

def sweep_portfolio_gates(
    portfolio_df: pd.DataFrame,
    span_years: float,
) -> list[dict]:
    """Single-gate sweep across all numeric signal columns + categorical checks."""
    rows: list[dict] = []

    baseline = compute_metrics(portfolio_df, span_years, MIN_TPY_PORTFOLIO)
    if baseline:
        rows.append({"gate": "no_gate", **baseline})

    num_cols = [
        c for c in portfolio_df.select_dtypes(include="number").columns
        if c not in _EXCLUDE_GATE
    ]

    for col in num_cols:
        series = portfolio_df[col].dropna()
        if len(series) < 50:
            continue
        for q in (0.25, 0.50, 0.75):
            thresh = round(float(series.quantile(q)), 2)
            for op, mask in [
                (f">={thresh}", portfolio_df[col] >= thresh),
                (f"<={thresh}", portfolio_df[col] <= thresh),
            ]:
                m = compute_metrics(portfolio_df[mask.fillna(False)], span_years, MIN_TPY_PORTFOLIO)
                if m:
                    rows.append({"gate": f"{col}{op}", **m})

    for col in ["conflicted_tf", "session_directional_bias", "aoi_classification"]:
        if col not in portfolio_df.columns:
            continue
        m_null = compute_metrics(portfolio_df[portfolio_df[col].isna()], span_years, MIN_TPY_PORTFOLIO)
        if m_null:
            rows.append({"gate": f"{col}_null", **m_null})
        m_notnull = compute_metrics(portfolio_df[portfolio_df[col].notna()], span_years, MIN_TPY_PORTFOLIO)
        if m_notnull:
            rows.append({"gate": f"{col}_not_null", **m_notnull})

    if "trend_alignment_strength" in portfolio_df.columns:
        for v in [1, 2, 3]:
            m = compute_metrics(
                portfolio_df[portfolio_df["trend_alignment_strength"] >= v],
                span_years, MIN_TPY_PORTFOLIO,
            )
            if m:
                rows.append({"gate": f"trend_align>={v}", **m})

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years | %d rows (RR=%.1f)", span_years, len(df), RR)

    zone_dist = df.groupby(["direction", "htf_zone"]).size().to_dict()
    logger.info("Zone distribution: %s", zone_dist)

    breakdown_rows: list[dict] = []
    portfolio_parts: list[pd.DataFrame] = []

    # Expected hypothesis: bearish@premium + bullish@discount have edge
    # Also test the inverse combos to confirm they're weak
    combos = [
        ("bearish", "premium"),
        ("bullish", "discount"),
        ("bearish", "discount"),
        ("bullish", "premium"),
    ]

    for group_name, symbols in EXCLUSIVE_GROUPS.items():
        group_df = df[df["symbol"].isin(symbols)].copy()
        logger.info("[%s] %d total rows", group_name, len(group_df))

        for direction, zone in combos:
            bucket_df = group_df[
                (group_df["direction"] == direction) &
                (group_df["htf_zone"] == zone)
            ]

            if len(bucket_df) < 50:
                logger.debug(
                    "  [%s|%s@%s] too few rows (%d), skip",
                    group_name, direction, zone, len(bucket_df),
                )
                continue

            viable = sweep_bucket(bucket_df, span_years)

            if not viable:
                logger.info("  [%s|%s@%s] no viable config", group_name, direction, zone)
                continue

            best = viable[0]
            logger.info(
                "  [%s|%s@%s] best: %s/%s  win=%.4f  tpy=%.1f  exp=%.4f  mls=%d  (%d viable)",
                group_name, direction, zone,
                best["sl_model"], best["window"],
                best["win_pct"], best["tpy"], best["expectancy_r"],
                best["max_losing_streak"], len(viable),
            )

            for r in viable[:5]:
                breakdown_rows.append({
                    "group": group_name,
                    "direction": direction,
                    "zone": zone,
                    **r,
                })

            # Only add hypothesis-aligned combos to portfolio
            if (direction == "bearish" and zone == "premium") or \
               (direction == "bullish" and zone == "discount"):
                best_hours = set(best["window_hours"])
                port_slice = bucket_df[
                    (bucket_df["sl_model"] == best["sl_model"]) &
                    (bucket_df["hour_of_day_utc"].isin(best_hours))
                ].copy()
                port_slice["_bucket"] = f"{group_name}|{direction}|{zone}"
                portfolio_parts.append(port_slice)

    # Save breakdown
    if breakdown_rows:
        breakdown_df = (
            pd.DataFrame(breakdown_rows)
            .sort_values(["zone", "direction", "win_pct"], ascending=[True, True, False])
        )
        breakdown_df.to_csv(BREAKDOWN_OUT, index=False)
        logger.info("Saved %d breakdown rows → %s", len(breakdown_df), BREAKDOWN_OUT)

        display_cols = ["group", "direction", "zone", "sl_model", "window",
                        "n_trades", "tpy", "win_pct", "expectancy_r", "max_losing_streak"]
        avail = [c for c in display_cols if c in breakdown_df.columns]

        logger.info("=== ALL VIABLE BUCKET CONFIGS (sorted by win_pct) ===")
        logger.info(
            "\n%s",
            breakdown_df.sort_values("win_pct", ascending=False)[avail].to_string(index=False),
        )

        logger.info("=== HYPOTHESIS CHECK ===")
        for direction, zone, label in [
            ("bearish", "premium", "HYPOTHESIS (expected GOOD)"),
            ("bullish", "discount", "HYPOTHESIS (expected GOOD)"),
            ("bearish", "discount", "INVERSE (expected WEAK)"),
            ("bullish", "premium", "INVERSE (expected WEAK)"),
        ]:
            subset = breakdown_df[
                (breakdown_df["direction"] == direction) &
                (breakdown_df["zone"] == zone)
            ]
            if subset.empty:
                logger.info("  %s@%s [%s]: no viable configs", direction, zone, label)
            else:
                best = subset.sort_values("win_pct", ascending=False).iloc[0]
                logger.info(
                    "  %s@%s [%s]: %d configs, best win=%.4f tpy=%.1f (%s | %s/%s)",
                    direction, zone, label, len(subset),
                    best["win_pct"], best["tpy"], best["group"],
                    best["sl_model"], best["window"],
                )

    # Portfolio gate sweep
    if not portfolio_parts:
        logger.warning("No hypothesis-aligned viable configs — portfolio empty")
        return

    portfolio_df = pd.concat(portfolio_parts, ignore_index=True)
    buckets = portfolio_df["_bucket"].unique().tolist()
    logger.info(
        "Portfolio pre-gate: %d trades | %.1f tpy | %d buckets",
        len(portfolio_df), len(portfolio_df) / span_years, len(buckets),
    )
    for b in buckets:
        sl_b = portfolio_df[portfolio_df["_bucket"] == b]
        logger.info("  %s: %d trades (%.1f tpy)", b, len(sl_b), len(sl_b) / span_years)

    gate_rows = sweep_portfolio_gates(portfolio_df, span_years)

    if gate_rows:
        results_df = pd.DataFrame(gate_rows)
        results_df.to_csv(RESULTS_OUT, index=False)
        logger.info("Saved %d gate results → %s", len(results_df), RESULTS_OUT)

        display_cols = ["gate", "n_trades", "tpy", "win_pct",
                        "expectancy_r", "max_losing_streak", "profit_factor"]
        avail = [c for c in display_cols if c in results_df.columns]

        logger.info("=== TOP 20 BY WIN_PCT ===")
        logger.info("\n%s", results_df[avail].head(20).to_string(index=False))

        logger.info("=== PARETO: win_pct >= 0.40 AND tpy >= 100 ===")
        pareto = results_df[
            (results_df["win_pct"] >= 0.40) &
            (results_df["tpy"] >= 100)
        ].sort_values("tpy", ascending=False)
        if not pareto.empty:
            logger.info("\n%s", pareto[avail].to_string(index=False))
        else:
            logger.info("  No configs meet both criteria — relaxing to win>=0.38 & tpy>=100:")
            relaxed = results_df[
                (results_df["win_pct"] >= 0.38) &
                (results_df["tpy"] >= 100)
            ].sort_values("win_pct", ascending=False)
            if not relaxed.empty:
                logger.info("\n%s", relaxed[avail].to_string(index=False))
            else:
                logger.info("  Still empty")

        logger.info("=== TOP 10 BY EXPECTANCY ===")
        logger.info(
            "\n%s",
            results_df.sort_values("expectancy_r", ascending=False)[avail].head(10).to_string(index=False),
        )


if __name__ == "__main__":
    main()
