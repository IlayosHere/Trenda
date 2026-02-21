#!/usr/bin/env python3
"""
rebalance_portfolio.py

Strategy: Quality bull + Volume bear.
- Bull: use per-group tight gates (retain≥40%) for high win%
- Bear: expand windows, add more buckets, try wider hours to gain volume
- Target: 100+ tpy total with high overall win%

Bear side expansion levers:
  1. Widen existing bear windows (expand ±1-3h)
  2. Add bear buckets that were previously excluded (e.g. 'mid' zone)
  3. Relax bear window tpy minimums
  4. Test different SL models that trade more frequently
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
MIN_TRADES: int = 15

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

# Per-group bull gates (retain≥40% winners from bull_group_gate_optimizer)
BULL_GROUP_GATES: dict[str, tuple[str, str, float]] = {
    "jpy_pairs":   ("signal_candle_opposite_extreme_atr", "<=", 0.7),  # 53.85%
    "usd_majors":  ("session_directional_bias", ">=", 0.2),             # 58.14%
    "eur_crosses": ("aoi_height_atr", "<=", 1.3),                      # 66.67%
    "gbp_crosses": ("session_directional_bias", ">=", 0.1),             # 61.11%
    "commodity":   ("distance_from_last_impulse_atr", "<=", 0.38),      # 49.12%
}

# Also test a milder bull gate set (retain≥50%)
BULL_GROUP_GATES_MILD: dict[str, tuple[str, str, float]] = {
    "jpy_pairs":   ("signal_candle_opposite_extreme_atr", "<=", 0.7),
    "usd_majors":  ("session_directional_bias", ">=", 0.2),
    "eur_crosses": ("aoi_height_atr", "<=", 1.3),
    "gbp_crosses": ("session_directional_bias", ">=", 0.1),
    "commodity":   ("session_directional_bias", ">=", 0.0),  # pass-through, nothing helps
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
    s = mx = 0
    for e in exits:
        if e == "SL":
            s += 1; mx = max(mx, s)
        elif e == "TP":
            s = 0
    return mx


def met(df: pd.DataFrame, sy: float, min_n: int = MIN_TRADES) -> Optional[dict]:
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


# ---------------------------------------------------------------------------
# Bull side: apply per-group gates + existing tuned windows
# ---------------------------------------------------------------------------
def build_quality_bull(df: pd.DataFrame, gate_map: dict) -> pd.DataFrame:
    """Bull portfolio with per-group gates applied on top of tuned windows."""
    bull = df[(df["direction"] == "bullish") & (df["session_directional_bias"] >= 0.0)]
    configs = pd.read_csv(TUNED_CSV)
    bull_cfgs = configs[configs["direction"] == "bullish"]
    parts = []
    for _, cfg in bull_cfgs.iterrows():
        grp = cfg["group"]
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bull[
            (bull["group"] == grp) &
            (bull["htf_zone"] == cfg["zone"]) &
            (bull["sl_model"] == cfg["sl_model"]) &
            (bull["hour_of_day_utc"].isin(hours))
        ]
        # Apply per-group gate
        if grp in gate_map:
            col, op, thresh = gate_map[grp]
            if op == ">=":
                sub = sub[sub[col] >= thresh]
            else:
                sub = sub[sub[col] <= thresh]
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Bear side: expand from tuned configs
# ---------------------------------------------------------------------------
def build_expanded_bear(
    df: pd.DataFrame,
    expand_hours: int = 0,
    include_mid: bool = False,
    min_win: float = 0.0,
) -> tuple[pd.DataFrame, list[dict]]:
    """Build expanded bear portfolio.
    
    expand_hours: expand each tuned window by this many hours (symmetric)
    include_mid: also scan 'mid' zone buckets
    min_win: minimum win% for new buckets
    """
    bear = df[(df["direction"] == "bearish") & (df["aoi_touch_count_since_creation"] <= 3)]
    configs = pd.read_csv(TUNED_CSV)
    bear_cfgs = configs[configs["direction"] == "bearish"]
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25

    parts = []
    used_configs = []

    # Existing bear buckets with optional window expansion
    for _, cfg in bear_cfgs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        if expand_hours > 0:
            # Expand symmetrically
            gap = sorted(set(range(24)) - hours)
            if gap:
                start = (gap[-1] + 1) % 24
                end = (gap[0] - 1) % 24
                for i in range(1, expand_hours + 1):
                    hours.add((start - i) % 24)
                    hours.add((end + i) % 24)

        sub = bear[
            (bear["group"] == cfg["group"]) &
            (bear["htf_zone"] == cfg["zone"]) &
            (bear["sl_model"] == cfg["sl_model"]) &
            (bear["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 5:
            parts.append(sub)
            used_configs.append({
                "group": cfg["group"], "direction": "bearish",
                "zone": cfg["zone"], "sl_model": cfg["sl_model"],
                "hours": sorted(hours), "source": "existing",
            })

    # Scan for new bear mid-zone buckets
    if include_mid:
        existing_keys = {(c["group"], c["zone"]) for c in used_configs}
        for grp in EXCLUSIVE_GROUPS:
            if (grp, "mid") in existing_keys:
                continue
            mid_bear = bear[
                (bear["group"] == grp) &
                (bear["htf_zone"] == "mid")
            ]
            if len(mid_bear) < 20:
                continue
            # Find best SL model + window
            best_cfg = None
            best_win = min_win
            for sl in mid_bear["sl_model"].unique():
                sl_sub = mid_bear[mid_bear["sl_model"] == sl]
                # Try windows 6h-16h
                for size in range(6, 17):
                    for start in range(24):
                        hrs = set((start + i) % 24 for i in range(size))
                        filtered = sl_sub[sl_sub["hour_of_day_utc"].isin(hrs)]
                        mm = met(filtered, sy)
                        if mm and mm["exp"] > 0 and mm["win"] > best_win:
                            best_win = mm["win"]
                            best_cfg = {
                                "group": grp, "direction": "bearish",
                                "zone": "mid", "sl_model": sl,
                                "hours": sorted(hrs), "source": "new_mid",
                                "win": mm["win"], "n": mm["n"],
                            }
                # Also all hours
                mm = met(sl_sub, sy)
                if mm and mm["exp"] > 0 and mm["win"] > best_win:
                    best_win = mm["win"]
                    best_cfg = {
                        "group": grp, "direction": "bearish",
                        "zone": "mid", "sl_model": sl,
                        "hours": list(range(24)), "source": "new_mid",
                        "win": mm["win"], "n": mm["n"],
                    }

            if best_cfg:
                sub = bear[
                    (bear["group"] == grp) &
                    (bear["htf_zone"] == "mid") &
                    (bear["sl_model"] == best_cfg["sl_model"]) &
                    (bear["hour_of_day_utc"].isin(set(best_cfg["hours"])))
                ]
                if len(sub) >= 10:
                    parts.append(sub)
                    used_configs.append(best_cfg)

    result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return result, used_configs


# ---------------------------------------------------------------------------
def show(label: str, pf: pd.DataFrame, sy: float) -> Optional[dict]:
    mm = met(pf, sy, 5)
    if not mm:
        return None
    flag = " ✓" if mm["tpy"] >= 100 else ""
    logger.info(
        "  %-50s  n=%4d  tpy=%6.1f  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f%s",
        label, mm["n"], mm["tpy"], mm["win"], mm["exp"], mm["mls"], mm["pf"], flag,
    )
    for d in ["bearish", "bullish"]:
        dm = met(pf[pf["direction"] == d], sy, 5)
        if dm:
            logger.info(
                "    %-10s  n=%4d  tpy=%5.1f  win=%5.2f%%  mls=%2d  pf=%.3f",
                d, dm["n"], dm["tpy"], dm["win"], dm["mls"], dm["pf"],
            )
    return mm


# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", sy, len(df))

    bear_gated = df[(df["direction"] == "bearish") & (df["aoi_touch_count_since_creation"] <= 3)]
    logger.info("Total bear gated (tc<=3): %d", len(bear_gated))

    # ===============================================================
    # BASELINE: Current tuned portfolio
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("BASELINE")
    logger.info("=" * 120)

    # Old bear
    configs = pd.read_csv(TUNED_CSV)
    bear_cfgs = configs[configs["direction"] == "bearish"]
    bear_parts = []
    for _, cfg in bear_cfgs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bear_gated[
            (bear_gated["group"] == cfg["group"]) &
            (bear_gated["htf_zone"] == cfg["zone"]) &
            (bear_gated["sl_model"] == cfg["sl_model"]) &
            (bear_gated["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 5:
            bear_parts.append(sub)
    old_bear = pd.concat(bear_parts, ignore_index=True)

    # Old bull
    bull_all = df[(df["direction"] == "bullish") & (df["session_directional_bias"] >= 0.0)]
    bull_cfgs = configs[configs["direction"] == "bullish"]
    bull_parts = []
    for _, cfg in bull_cfgs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bull_all[
            (bull_all["group"] == cfg["group"]) &
            (bull_all["htf_zone"] == cfg["zone"]) &
            (bull_all["sl_model"] == cfg["sl_model"]) &
            (bull_all["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 5:
            bull_parts.append(sub)
    old_bull = pd.concat(bull_parts, ignore_index=True)

    old_full = pd.concat([old_bear, old_bull], ignore_index=True)
    show("A. BASELINE (current tuned)", old_full, sy)

    # ===============================================================
    # Build quality bull variants
    # ===============================================================
    tight_bull = build_quality_bull(df, BULL_GROUP_GATES)
    mild_bull = build_quality_bull(df, BULL_GROUP_GATES_MILD)

    bull_m_tight = met(tight_bull, sy, 5)
    bull_m_mild = met(mild_bull, sy, 5)
    logger.info("\n  Bull quality variants:")
    if bull_m_tight:
        logger.info("    TIGHT gates:  n=%d  tpy=%.1f  win=%.2f%%",
                    bull_m_tight["n"], bull_m_tight["tpy"], bull_m_tight["win"])
    if bull_m_mild:
        logger.info("    MILD gates:   n=%d  tpy=%.1f  win=%.2f%%",
                    bull_m_mild["n"], bull_m_mild["tpy"], bull_m_mild["win"])

    # ===============================================================
    # Build expanded bear variants
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("BEAR EXPANSION OPTIONS")
    logger.info("=" * 120)

    # Variant 1: Expand existing windows +1h each side
    bear_exp1, bear_exp1_cfg = build_expanded_bear(df, expand_hours=1)
    # Variant 2: Expand +2h each side
    bear_exp2, bear_exp2_cfg = build_expanded_bear(df, expand_hours=2)
    # Variant 3: Expand +3h each side
    bear_exp3, bear_exp3_cfg = build_expanded_bear(df, expand_hours=3)
    # Variant 4: Original + mid zone
    bear_mid, bear_mid_cfg = build_expanded_bear(df, expand_hours=0, include_mid=True, min_win=45)
    # Variant 5: Expand +1h + mid zone
    bear_exp1_mid, bear_exp1_mid_cfg = build_expanded_bear(df, expand_hours=1, include_mid=True, min_win=45)
    # Variant 6: Expand +2h + mid zone
    bear_exp2_mid, bear_exp2_mid_cfg = build_expanded_bear(df, expand_hours=2, include_mid=True, min_win=42)

    for label, bdf in [
        ("Bear original", old_bear),
        ("Bear +1h", bear_exp1),
        ("Bear +2h", bear_exp2),
        ("Bear +3h", bear_exp3),
        ("Bear orig + mid", bear_mid),
        ("Bear +1h + mid", bear_exp1_mid),
        ("Bear +2h + mid", bear_exp2_mid),
    ]:
        bm = met(bdf, sy, 5)
        if bm:
            logger.info(
                "  %-25s  n=%4d  tpy=%5.1f  win=%5.2f%%  mls=%2d  pf=%.3f",
                label, bm["n"], bm["tpy"], bm["win"], bm["mls"], bm["pf"],
            )

    # Show new mid-zone buckets found
    for cfg in bear_mid_cfg + bear_exp1_mid_cfg + bear_exp2_mid_cfg:
        if cfg.get("source") == "new_mid":
            logger.info(
                "  NEW MID BUCKET: %s|bear|mid  SL=%s  win=%.1f%%  n=%d",
                cfg["group"], cfg["sl_model"], cfg.get("win", 0), cfg.get("n", 0),
            )

    # ===============================================================
    # Assemble combinations
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("FULL PORTFOLIO COMBINATIONS")
    logger.info("=" * 120)

    combos = [
        ("A. BASELINE", old_bear, old_bull),
        ("B. Tight bull + original bear", old_bear, tight_bull),
        ("C. Mild bull + original bear", old_bear, mild_bull),
        ("D. Tight bull + bear +1h", bear_exp1, tight_bull),
        ("E. Tight bull + bear +2h", bear_exp2, tight_bull),
        ("F. Tight bull + bear +3h", bear_exp3, tight_bull),
        ("G. Tight bull + bear +1h + mid", bear_exp1_mid, tight_bull),
        ("H. Tight bull + bear +2h + mid", bear_exp2_mid, tight_bull),
        ("I. Mild bull + bear +1h", bear_exp1, mild_bull),
        ("J. Mild bull + bear +2h", bear_exp2, mild_bull),
        ("K. Mild bull + bear +1h + mid", bear_exp1_mid, mild_bull),
        ("L. Mild bull + bear +2h + mid", bear_exp2_mid, mild_bull),
    ]

    for label, bear_pf, bull_pf in combos:
        full = pd.concat([bear_pf, bull_pf], ignore_index=True)
        show(label, full, sy)

    # ===============================================================
    # Year-over-year stability for top configs
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("YEAR-OVER-YEAR STABILITY (top 3 configs)")
    logger.info("=" * 120)

    top3 = [
        ("A. BASELINE", old_bear, old_bull),
        ("D. Tight bull + bear +1h", bear_exp1, tight_bull),
        ("I. Mild bull + bear +1h", bear_exp1, mild_bull),
    ]

    for label, bear_pf, bull_pf in top3:
        full = pd.concat([bear_pf, bull_pf], ignore_index=True)
        full_sorted = full.sort_values("signal_time")
        full_sorted["year"] = full_sorted["signal_time"].dt.year
        logger.info("\n  %s:", label)
        for year in sorted(full_sorted["year"].unique()):
            ydf = full_sorted[full_sorted["year"] == year]
            ym = met(ydf, 1.0, 5)
            if ym:
                logger.info(
                    "    %d: n=%3d  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f",
                    year, ym["n"], ym["win"], ym["exp"], ym["mls"], ym["pf"],
                )

    logger.info("\nDONE")


if __name__ == "__main__":
    main()
