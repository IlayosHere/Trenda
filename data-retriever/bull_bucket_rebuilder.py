#!/usr/bin/env python3
"""
bull_bucket_rebuilder.py

Rebuild bullish portfolio buckets from scratch with gates applied.
Anti-overfit rules:
  - Minimum 6h window (no 3h micro-windows)
  - Minimum 20 trades per bucket
  - Evaluate SL model first on ALL hours, then find best window
  - Compare "no zone split" vs zone split per group
  - Try dropping unviable buckets entirely

Bear side stays exactly as-is from tuned configs.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
MIN_TRADES: int = 20
MIN_WINDOW: int = 6  # minimum 6h window to prevent overfit

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
    return df


def _mls(exits: list[str]) -> int:
    streak = mx = 0
    for e in exits:
        if e == "SL":
            streak += 1
            mx = max(mx, streak)
        elif e == "TP":
            streak = 0
    return mx


def mets(df: pd.DataFrame, span_years: float, min_n: int = MIN_TRADES) -> Optional[dict]:
    if len(df) < min_n or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n":   len(df_s),
        "tpy": round(tpy, 1),
        "win": round(float((df_s["exit_reason"] == "TP").mean()) * 100, 2),
        "exp": round(exp_r, 4),
        "mls": _mls(df_s["exit_reason"].tolist()),
        "pf":  round(gp / max(gl, 1e-9), 3),
    }


def gen_windows(size: int) -> list[tuple[str, set[int]]]:
    windows = []
    for start in range(24):
        hours = set((start + i) % 24 for i in range(size))
        windows.append((f"h{start:02d}+{size}h", hours))
    return windows


# ---------------------------------------------------------------------------
# Step 1: Find best SL model per (group, zone) using ALL hours
# ---------------------------------------------------------------------------
def find_best_sl_models(bull_gated: pd.DataFrame, sy: float) -> dict:
    logger.info("\n" + "=" * 120)
    logger.info("STEP 1: Best SL model per (group, zone) — ALL hours, gated bull trades")
    logger.info("=" * 120)

    best_sl: dict = {}
    for grp in EXCLUSIVE_GROUPS:
        for zone in ["discount", "premium"]:
            sub = bull_gated[
                (bull_gated["group"] == grp) &
                (bull_gated["htf_zone"] == zone)
            ]
            if len(sub) < MIN_TRADES:
                continue

            sl_results = []
            for sl in sub["sl_model"].unique():
                sl_sub = sub[sub["sl_model"] == sl]
                m = mets(sl_sub, sy, 15)
                if m and m["exp"] > 0:
                    sl_results.append({"sl_model": sl, **m})

            if not sl_results:
                continue

            sl_df = pd.DataFrame(sl_results).sort_values("win", ascending=False)
            best = sl_df.iloc[0]
            best_sl[f"{grp}|{zone}"] = {
                "group": grp, "zone": zone,
                "sl_model": best["sl_model"],
                "all_hours_win": best["win"],
                "all_hours_n": best["n"],
            }
            logger.info(
                "  %-30s  BEST SL=%-30s  n=%3d  win=%.2f%%  (pool all SLs=%d)",
                f"{grp}|{zone}", best["sl_model"],
                int(best["n"]), best["win"], len(sub),
            )
            # Show all SL models
            disp = ["sl_model", "n", "tpy", "win", "exp", "mls", "pf"]
            logger.info("\n%s\n", sl_df[disp].head(5).to_string(index=False))

    return best_sl


# ---------------------------------------------------------------------------
# Step 2: Find best window per (group, zone) for the selected SL model
# ---------------------------------------------------------------------------
def find_best_windows(
    bull_gated: pd.DataFrame, sy: float, best_sl: dict,
) -> list[dict]:
    logger.info("\n" + "=" * 120)
    logger.info("STEP 2: Best hour window per bucket (min %dh)", MIN_WINDOW)
    logger.info("=" * 120)

    configs = []
    for key, info in best_sl.items():
        grp = info["group"]
        zone = info["zone"]
        sl_model = info["sl_model"]

        sub = bull_gated[
            (bull_gated["group"] == grp) &
            (bull_gated["htf_zone"] == zone) &
            (bull_gated["sl_model"] == sl_model)
        ]

        # Sweep windows from MIN_WINDOW to 16h
        results = []
        for size in range(MIN_WINDOW, 17):
            for label, hours in gen_windows(size):
                filtered = sub[sub["hour_of_day_utc"].isin(hours)]
                m = mets(filtered, sy)
                if m and m["exp"] > 0:
                    results.append({
                        "window": label,
                        "hours": sorted(hours),
                        "size": size,
                        **m,
                    })

        # Also test ALL hours (no window restriction)
        m_all = mets(sub, sy)
        if m_all and m_all["exp"] > 0:
            results.append({
                "window": "ALL_24h",
                "hours": list(range(24)),
                "size": 24,
                **m_all,
            })

        if not results:
            continue

        rdf = pd.DataFrame(results).sort_values("win", ascending=False)

        # Pick best that meets min trades
        best = rdf.iloc[0]
        cfg = {
            "group": grp,
            "direction": "bullish",
            "zone": zone,
            "sl_model": sl_model,
            "hours": best["hours"],
            "window": best["window"],
            "win": best["win"],
            "n": best["n"],
            "tpy": best["tpy"],
            "mls": best["mls"],
        }
        configs.append(cfg)

        logger.info(
            "\n--- %s  SL=%s ---  BEST: %s win=%.2f%% n=%d",
            key, sl_model, best["window"], best["win"], int(best["n"]),
        )
        disp = ["window", "size", "n", "tpy", "win", "exp", "mls", "pf"]
        logger.info("\n%s", rdf[disp].head(10).to_string(index=False))

    return configs


# ---------------------------------------------------------------------------
# Step 3: Also try NO zone split (group-level only)
# ---------------------------------------------------------------------------
def find_group_level_configs(bull_gated: pd.DataFrame, sy: float) -> list[dict]:
    logger.info("\n" + "=" * 120)
    logger.info("STEP 3: Group-level configs (no zone split) — is zoning even helping?")
    logger.info("=" * 120)

    configs = []
    for grp in EXCLUSIVE_GROUPS:
        sub = bull_gated[bull_gated["group"] == grp]
        if len(sub) < MIN_TRADES:
            continue

        # Find best SL model across all zones
        best_sl = None
        best_win = 0
        for sl in sub["sl_model"].unique():
            sl_sub = sub[sub["sl_model"] == sl]
            m = mets(sl_sub, sy, 15)
            if m and m["exp"] > 0 and m["win"] > best_win:
                best_win = m["win"]
                best_sl = sl

        if best_sl is None:
            continue

        sl_sub = sub[sub["sl_model"] == best_sl]

        # Find best window
        results = []
        for size in range(MIN_WINDOW, 17):
            for label, hours in gen_windows(size):
                filtered = sl_sub[sl_sub["hour_of_day_utc"].isin(hours)]
                m = mets(filtered, sy)
                if m and m["exp"] > 0:
                    results.append({
                        "window": label, "hours": sorted(hours), "size": size, **m,
                    })

        m_all = mets(sl_sub, sy)
        if m_all and m_all["exp"] > 0:
            results.append({
                "window": "ALL_24h", "hours": list(range(24)), "size": 24, **m_all,
            })

        if not results:
            continue

        rdf = pd.DataFrame(results).sort_values("win", ascending=False)
        best = rdf.iloc[0]
        configs.append({
            "group": grp, "direction": "bullish", "zone": "all",
            "sl_model": best_sl, "hours": best["hours"],
            "window": best["window"], "win": best["win"],
            "n": best["n"], "tpy": best["tpy"],
        })
        logger.info(
            "  %-15s  SL=%-30s  %s  n=%d  win=%.2f%%  tpy=%.1f",
            grp, best_sl, best["window"], int(best["n"]), best["win"], best["tpy"],
        )

    return configs


# ---------------------------------------------------------------------------
# Step 4: Build and compare portfolios
# ---------------------------------------------------------------------------
def build_bear_portfolio(bear_gated: pd.DataFrame) -> pd.DataFrame:
    """Build bear side from tuned configs."""
    configs = pd.read_csv(TUNED_CSV)
    bear_cfgs = configs[configs["direction"] == "bearish"]
    parts = []
    for _, cfg in bear_cfgs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bear_gated[
            (bear_gated["group"] == cfg["group"]) &
            (bear_gated["htf_zone"] == cfg["zone"]) &
            (bear_gated["sl_model"] == cfg["sl_model"]) &
            (bear_gated["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_bull_portfolio(bull_gated: pd.DataFrame, configs: list[dict]) -> pd.DataFrame:
    parts = []
    for cfg in configs:
        hours = set(cfg["hours"])
        if cfg.get("zone") == "all":
            sub = bull_gated[
                (bull_gated["group"] == cfg["group"]) &
                (bull_gated["sl_model"] == cfg["sl_model"]) &
                (bull_gated["hour_of_day_utc"].isin(hours))
            ]
        else:
            sub = bull_gated[
                (bull_gated["group"] == cfg["group"]) &
                (bull_gated["htf_zone"] == cfg["zone"]) &
                (bull_gated["sl_model"] == cfg["sl_model"]) &
                (bull_gated["hour_of_day_utc"].isin(hours))
            ]
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def show_portfolio(label: str, pf: pd.DataFrame, sy: float) -> Optional[dict]:
    m = mets(pf, sy, 10)
    if m:
        flag = " ✓" if m["tpy"] >= 100 else ""
        logger.info(
            "  %-35s  n=%4d  tpy=%6.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f%s",
            label, m["n"], m["tpy"], m["win"], m["exp"], m["mls"], m["pf"], flag,
        )
        # Per direction
        for d in ["bearish", "bullish"]:
            dm = mets(pf[pf["direction"] == d], sy, 5)
            if dm:
                logger.info(
                    "    %-10s  n=%4d  tpy=%5.1f  win=%5.2f%%  mls=%2d",
                    d, dm["n"], dm["tpy"], dm["win"], dm["mls"],
                )
    return m


# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", sy, len(df))

    # Apply gates
    bear_gated = df[(df["direction"] == "bearish") & (df["aoi_touch_count_since_creation"] <= 3)]
    bull_gated = df[(df["direction"] == "bullish") & (df["session_directional_bias"] >= 0.0)]
    logger.info("Bear gated: %d | Bull gated: %d", len(bear_gated), len(bull_gated))

    # Bear side stays fixed
    bear_pf = build_bear_portfolio(bear_gated)
    logger.info("Bear portfolio (fixed from tuned): %d trades", len(bear_pf))

    # Step 1-2: Zoned bull configs
    best_sl = find_best_sl_models(bull_gated, sy)
    zoned_configs = find_best_windows(bull_gated, sy, best_sl)

    # Step 3: Group-level (no zone) bull configs
    group_configs = find_group_level_configs(bull_gated, sy)

    # Step 4: Build and compare
    logger.info("\n" + "=" * 120)
    logger.info("STEP 4: PORTFOLIO COMPARISON")
    logger.info("=" * 120)

    # Old bull side from tuned configs
    old_tuned = pd.read_csv(TUNED_CSV)
    old_bull_cfgs = old_tuned[old_tuned["direction"] == "bullish"].to_dict("records")
    for cfg in old_bull_cfgs:
        cfg["hours"] = ast.literal_eval(str(cfg["hours"]))
    old_bull_pf = build_bull_portfolio(bull_gated, old_bull_cfgs)
    old_full = pd.concat([bear_pf, old_bull_pf], ignore_index=True)

    # New zoned bull
    new_bull_pf = build_bull_portfolio(bull_gated, zoned_configs)
    new_full = pd.concat([bear_pf, new_bull_pf], ignore_index=True)

    # New group-level bull
    grp_bull_pf = build_bull_portfolio(bull_gated, group_configs)
    grp_full = pd.concat([bear_pf, grp_bull_pf], ignore_index=True)

    # Hybrid: use zoned where viable, group-level where not
    # Drop weak zoned buckets (win < 42%) and replace with group-level
    viable_zoned = [c for c in zoned_configs if c["win"] >= 42]
    weak_groups = {c["group"] for c in zoned_configs if c["win"] < 42}
    hybrid_cfgs = list(viable_zoned) + [c for c in group_configs if c["group"] in weak_groups]
    hybrid_bull_pf = build_bull_portfolio(bull_gated, hybrid_cfgs)
    hybrid_full = pd.concat([bear_pf, hybrid_bull_pf], ignore_index=True)

    # Also try: just drop commodity bull entirely
    no_comm_configs = [c for c in zoned_configs if c["group"] != "commodity"]
    no_comm_bull_pf = build_bull_portfolio(bull_gated, no_comm_configs)
    no_comm_full = pd.concat([bear_pf, no_comm_bull_pf], ignore_index=True)

    logger.info("")
    show_portfolio("A. OLD tuned (reference)", old_full, sy)
    show_portfolio("B. NEW zoned bull (rebuilt)", new_full, sy)
    show_portfolio("C. Group-level bull (no zones)", grp_full, sy)
    show_portfolio("D. Hybrid (viable zoned + group)", hybrid_full, sy)
    show_portfolio("E. Drop commodity bull entirely", no_comm_full, sy)

    # Show new bull configs
    logger.info("\n  === NEW ZONED BULL CONFIGS ===")
    for cfg in zoned_configs:
        logger.info(
            "    %-15s %-10s SL=%-30s %-10s  n=%3d  win=%.1f%%  tpy=%.1f",
            cfg["group"], cfg["zone"], cfg["sl_model"],
            cfg["window"], cfg["n"], cfg["win"], cfg["tpy"],
        )

    logger.info("\n  === GROUP-LEVEL BULL CONFIGS ===")
    for cfg in group_configs:
        logger.info(
            "    %-15s SL=%-30s %-10s  n=%3d  win=%.1f%%  tpy=%.1f",
            cfg["group"], cfg["sl_model"],
            cfg["window"], cfg["n"], cfg["win"], cfg["tpy"],
        )

    # Save
    out = ANALYSIS_DIR / "rebuilt_bull_configs.csv"
    pd.DataFrame(zoned_configs).to_csv(out, index=False)
    logger.info("\nSaved zoned configs → %s", out)

    out2 = ANALYSIS_DIR / "rebuilt_bull_group_configs.csv"
    pd.DataFrame(group_configs).to_csv(out2, index=False)
    logger.info("Saved group configs → %s", out2)


if __name__ == "__main__":
    main()
