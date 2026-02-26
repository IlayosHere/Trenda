#!/usr/bin/env python3
"""
portfolio_finder_v5.py — 7-fold LOO portfolio discovery.

vs v4: no fixed holdout year. All 7 years [2019-2025] rotate as holdout in Stage 3.

Stage 3 (cell LOO): exp > 0 + n >= 10 per fold, 6/7 pass.
  Win% is NOT tested per fold — cells have 10-25 trades/year, SE ~±12%, making
  a per-fold 40% threshold a noise test rather than an edge test.

Stage 4 (portfolio per year): every year must have >= 100 trades, exp > 0,
  AND win >= 40%. At 100+ trades/year SE ~±5% — statistically meaningful.

Portfolio hard constraints (Stage 4):
  - Every individual year >= 100 trades
  - Every year exp > 0
  - Every year win >= 40%
  - Overall portfolio win >= 40%

Max gate depth: 2 (depth-3 removed — too few per-year samples for reliable LOO).
Gate sweep on all 7 years (pre-defined thresholds, not data-fit — minimal leakage).
Sensitivity filter retained: depth-1 gates only enter depth-2 combos if a
neighbouring threshold also beats baseline on the same column.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import psycopg2

from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
ALL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
N_YEARS   = len(ALL_YEARS)  # 7

RR        = 2.0
BREAKEVEN = 100.0 / (1.0 + RR)  # 33.33%

# LOO thresholds (Stage 3) — win% NOT tested here; see Stage 4 for portfolio-level win
LOO_MIN_PASS      = 6     # primary: config must survive 6/7 folds
LOO_FALLBACK_PASS = 5     # fallback for cells with zero 6/7 configs
LOO_FALLBACK_TPY  = 25    # fallback configs must also have TPY >= this
LOO_MIN_FOLD_N    = 10    # trades in a fold < this => fold counts as FAIL

# Portfolio per-year win floor — applied in Stage 4 where n >= 100 makes it meaningful
PORT_WIN_PER_YEAR = 40.0

# Gate sweep / cell minimums (all 7 years)
MIN_TPY_CELL = 12
MIN_N_CELL   = 60

# Depth penalty: prefer fewer gates
DEPTH_PENALTY: dict[int, float] = {0: 1.0, 1: 0.85, 2: 0.70}

# Suspicion penalty: extreme win% lift vs baseline likely signals overfit
WIN_SUSPICION_DELTA = 8.0   # gate win% - cell baseline win% threshold
WIN_SUSPICION_MULT  = 0.75  # adj_contrib multiplier when triggered

# Portfolio constraints (Stage 4)
MIN_PORT_TRADES_PER_YR = 100  # HARD: every year needs >= this many portfolio trades
MIN_PORT_TPY           = 100  # average TPY across all 7 years
MIN_PORT_WIN           = 40.0  # overall portfolio win% floor
MAX_SKIPPED_CELLS      = 4    # at most 4 of 10 cells can be skipped

GROUPS = {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}
_S2G = {s: g for g, ss in GROUPS.items() for s in ss}

_SQL = """\
SELECT
    es.id, es.signal_time, es.symbol, es.direction,
    es.trend_alignment_strength, es.hour_of_day_utc,
    es.aoi_touch_count_since_creation,
    es.max_retest_penetration_atr, es.bars_between_retest_and_break,
    es.conflicted_tf,
    pec.htf_range_position_mid, pec.htf_range_position_high,
    pec.session_directional_bias,
    pec.break_close_location, pec.break_impulse_range_atr,
    pec.break_impulse_body_atr, pec.retest_candle_body_penetration,
    pec.aoi_height_atr, pec.distance_to_next_htf_obstacle_atr,
    pec.distance_from_last_impulse_atr,
    pec.recent_trend_payoff_atr_24h, pec.recent_trend_payoff_atr_48h,
    pec.aoi_time_since_last_touch, pec.aoi_last_reaction_strength,
    pec.htf_range_size_mid_atr,
    pec.aoi_midpoint_range_position_mid,
    pec.trend_age_bars_1h, pec.trend_age_impulses,
    sg.signal_candle_opposite_extreme_atr AS opp_extreme,
    sg.signal_candle_range_atr, sg.signal_candle_body_atr,
    sg.aoi_near_edge_atr, sg.aoi_far_edge_atr,
    esi.sl_model, esi.exit_reason, esi.return_r
FROM trenda_replay.entry_signal          es
JOIN trenda_replay.pre_entry_context_v2  pec ON pec.entry_signal_id = es.id
JOIN trenda_replay.sl_geometry_unbiased  sg  ON sg.entry_signal_id  = es.id
JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
  AND esi.rr_multiple         = 2.0
ORDER BY es.signal_time
"""


def load_data() -> pd.DataFrame:
    cfg = {k: v for k, v in POSTGRES_DB.items() if k != "options"}
    cfg["options"] = "-c search_path=trenda_replay,public"
    logger.info("Loading data ...")
    with psycopg2.connect(**cfg) as conn:
        df = pd.read_sql_query(_SQL, conn)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"]        = df["signal_time"].dt.year
    df["group"]       = df["symbol"].map(_S2G)
    df["win"]         = (df["exit_reason"] == "TP").astype(int)
    df["is_sl"]       = (df["exit_reason"] == "SL").astype(int)
    df["zone"]        = np.where(df["htf_range_position_mid"] <= 0.25, "disc",
                        np.where(df["htf_range_position_mid"] >= 0.75, "prem", "mid"))
    df["body_ratio"]  = (
        df["signal_candle_body_atr"].fillna(0)
        / df["signal_candle_range_atr"].fillna(1).clip(lower=0.001)
    )
    logger.info("Loaded %d rows, %d signals", len(df), df["id"].nunique())
    return df


# ── Metrics ────────────────────────────────────────────────────────────────────
def M(df: pd.DataFrame, span: float = N_YEARS, label: str = "") -> dict:
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0, "tpy": 0.0, "win": 0.0,
                "exp": 0.0, "pf": 0.0, "mls": 0, "contribution": 0.0}
    tpy = n / span
    w   = 100.0 * df["win"].sum() / n
    e   = float(df["return_r"].mean())
    gp  = float(df.loc[df["return_r"] > 0, "return_r"].sum())
    gl  = float(abs(df.loc[df["return_r"] < 0, "return_r"].sum()))
    pf  = gp / gl if gl > 0 else 99.0
    streak = mx = 0
    for x in df.sort_values("signal_time")["is_sl"].values:
        if x:
            streak += 1
            mx = max(mx, streak)
        else:
            streak = 0
    return {
        "label": label, "n": n, "tpy": round(tpy, 1), "win": round(w, 2),
        "exp": round(e, 4), "pf": round(pf, 3), "mls": mx,
        "contribution": round(e * tpy, 2),
    }


# ── Gate families for sensitivity check ───────────────────────────────────────
# Each family lists adjacent thresholds on the same column.
# A gate is "sensitive" if at least one neighbour also beats baseline.
_GATE_FAMILIES: dict[str, list[str]] = {
    "hp<=":       ["hp<=0.3",       "hp<=0.5"],
    "hp>=":       ["hp>=0.5",       "hp>=0.7"],
    "tc<=":       ["tc<=2",         "tc<=5"],
    "sb>=":       ["sb>=-0.5",      "sb>=-0.2",    "sb>=0.0",  "sb>=0.2",  "sb>=0.5"],
    "opp<=":      ["opp<=0.4",      "opp<=0.7",    "opp<=1.0"],
    "imp>=":      ["imp>=0.5",      "imp>=1.0",    "imp>=2.0"],
    "bcl>=":      ["bcl>=0.5",      "bcl>=0.7"],
    "ah<=":       ["ah<=0.5",       "ah<=1.0"],
    "obs>=":      ["obs>=1.0",      "obs>=2.0"],
    "rp<=":       ["rp<=0.3",       "rp<=0.7"],
    "pay24>=":    ["pay24>=-0.5",   "pay24>=0.0",  "pay24>=1.0"],
    "pay48>=":    ["pay48>=-0.5",   "pay48>=0.0",  "pay48>=1.0"],
    "react>=":    ["react>=0.5",    "react>=1.5"],
    "d_imp<=":    ["d_imp<=1.0",    "d_imp<=2.0"],
    "br>=":       ["br>=0.5",       "br>=0.7"],
    "age<=":      ["age<=30",       "age<=80"],
    "bars_rb<=":  ["bars_rb<=2",    "bars_rb<=5"],
    "retest_p<=": ["retest_p<=0.5", "retest_p<=1.0"],
    "rng<=":      ["rng<=3.0",      "rng<=5.0"],
    "imp_b>=":    ["imp_b>=0.3",    "imp_b>=0.8"],
    "last_t>=":   ["last_t>=10",    "last_t>=50"],
    "hph<=":      ["hph<=0.3",      "hph<=0.5"],
    "hph>=":      ["hph>=0.5",      "hph>=0.7"],
    "amid<=":     ["amid<=0.3",     "amid<=0.5"],
    "amid>=":     ["amid>=0.5",     "amid>=0.7"],
    "t_imp<=":    ["t_imp<=2",      "t_imp<=5"],
    "sc_rng<=":   ["sc_rng<=0.5",   "sc_rng<=1.0"],
    "near>=":     ["near>=0.3",     "near>=0.8"],
}


def _adj_contrib(m: dict, cell_base_win: float, depth: int) -> float:
    mult = DEPTH_PENALTY.get(depth, 0.5)
    if m["win"] - cell_base_win > WIN_SUSPICION_DELTA:
        mult *= WIN_SUSPICION_MULT
    return m["contribution"] * mult


def _gate_is_sensitive(gname: str, gate_exp: dict[str, float], base_exp: float) -> bool:
    """True if gname has >= 1 adjacent-threshold gate that also beats base_exp."""
    for family in _GATE_FAMILIES.values():
        if gname in family:
            idx       = family.index(gname)
            neighbors = []
            if idx > 0:
                neighbors.append(family[idx - 1])
            if idx < len(family) - 1:
                neighbors.append(family[idx + 1])
            if not neighbors:
                return True  # only member in family
            return any(gate_exp.get(nb, -999.0) > base_exp for nb in neighbors)
    return True  # categorical / singleton — always OK


# ── Gate library (direction-aware) ────────────────────────────────────────────
def gate_lib(direction: str) -> list[tuple[str, object]]:
    G: list[tuple[str, object]] = []
    is_bull = direction == "bullish"

    if is_bull:
        G.append(("zone=disc",  lambda d: d[d["zone"] == "disc"]))
        G.append(("zone!=prem", lambda d: d[d["zone"] != "prem"]))
        for v in [0.3, 0.5]:
            G.append((f"hp<={v}", lambda d, v=v: d[d["htf_range_position_mid"].fillna(0.5) <= v]))
    else:
        G.append(("zone=prem",  lambda d: d[d["zone"] == "prem"]))
        G.append(("zone!=disc", lambda d: d[d["zone"] != "disc"]))
        for v in [0.5, 0.7]:
            G.append((f"hp>={v}", lambda d, v=v: d[d["htf_range_position_mid"].fillna(0.5) >= v]))

    for v in [2, 5]:
        G.append((f"tc<={v}", lambda d, v=v: d[d["aoi_touch_count_since_creation"] <= v]))

    for v in [-0.5, -0.2, 0.0, 0.2, 0.5]:
        G.append((f"sb>={v}", lambda d, v=v: d[d["session_directional_bias"].fillna(-99) >= v]))

    for v in [0.4, 0.7, 1.0]:
        G.append((f"opp<={v}", lambda d, v=v: d[d["opp_extreme"].fillna(99) <= v]))

    for v in [0.5, 1.0, 2.0]:
        G.append((f"imp>={v}", lambda d, v=v: d[d["break_impulse_range_atr"].fillna(0) >= v]))

    for v in [0.5, 0.7]:
        G.append((f"bcl>={v}", lambda d, v=v: d[d["break_close_location"].fillna(0) >= v]))

    for v in [0.5, 1.0]:
        G.append((f"ah<={v}", lambda d, v=v: d[d["aoi_height_atr"].fillna(99) <= v]))

    for v in [1.0, 2.0]:
        G.append((f"obs>={v}", lambda d, v=v: d[d["distance_to_next_htf_obstacle_atr"].fillna(0) >= v]))

    G.append(("al>=2",   lambda d: d[d["trend_alignment_strength"] >= 2]))
    G.append(("al=3",    lambda d: d[d["trend_alignment_strength"] == 3]))
    G.append(("no_conf", lambda d: d[d["conflicted_tf"].isna()]))

    for v in [0.3, 0.7]:
        G.append((f"rp<={v}", lambda d, v=v: d[d["retest_candle_body_penetration"].fillna(99) <= v]))

    for v in [-0.5, 0.0, 1.0]:
        G.append((f"pay24>={v}", lambda d, v=v: d[d["recent_trend_payoff_atr_24h"].fillna(-99) >= v]))
        G.append((f"pay48>={v}", lambda d, v=v: d[d["recent_trend_payoff_atr_48h"].fillna(-99) >= v]))

    for v in [0.5, 1.5]:
        G.append((f"react>={v}", lambda d, v=v: d[d["aoi_last_reaction_strength"].fillna(0) >= v]))

    for v in [1.0, 2.0]:
        G.append((f"d_imp<={v}", lambda d, v=v: d[d["distance_from_last_impulse_atr"].fillna(99) <= v]))

    for v in [0.5, 0.7]:
        G.append((f"br>={v}", lambda d, v=v: d[d["body_ratio"] >= v]))

    for v in [30, 80]:
        G.append((f"age<={v}", lambda d, v=v: d[d["trend_age_bars_1h"].fillna(999) <= v]))

    for nm, hrs in {"xh0-3": [0, 1, 2, 3], "xh21-23": [21, 22, 23]}.items():
        G.append((nm, lambda d, h=hrs: d[~d["hour_of_day_utc"].isin(h)]))

    for nm, hrs in {"LON+NY": list(range(7, 17)), "LON": list(range(7, 12))}.items():
        G.append((nm, lambda d, h=hrs: d[d["hour_of_day_utc"].isin(h)]))

    for v in [2, 5]:
        G.append((f"bars_rb<={v}", lambda d, v=v: d[d["bars_between_retest_and_break"].fillna(99) <= v]))

    for v in [0.5, 1.0]:
        G.append((f"retest_p<={v}", lambda d, v=v: d[d["max_retest_penetration_atr"].fillna(99) <= v]))

    for v in [3.0, 5.0]:
        G.append((f"rng<={v}", lambda d, v=v: d[d["htf_range_size_mid_atr"].fillna(99) <= v]))

    for v in [0.3, 0.8]:
        G.append((f"imp_b>={v}", lambda d, v=v: d[d["break_impulse_body_atr"].fillna(0) >= v]))

    for v in [10, 50]:
        G.append((f"last_t>={v}", lambda d, v=v: d[d["aoi_time_since_last_touch"].fillna(0) >= v]))

    if is_bull:
        for v in [0.3, 0.5]:
            G.append((f"hph<={v}", lambda d, v=v: d[d["htf_range_position_high"].fillna(0.5) <= v]))
    else:
        for v in [0.5, 0.7]:
            G.append((f"hph>={v}", lambda d, v=v: d[d["htf_range_position_high"].fillna(0.5) >= v]))

    if is_bull:
        for v in [0.3, 0.5]:
            G.append((f"amid<={v}", lambda d, v=v: d[d["aoi_midpoint_range_position_mid"].fillna(0.5) <= v]))
    else:
        for v in [0.5, 0.7]:
            G.append((f"amid>={v}", lambda d, v=v: d[d["aoi_midpoint_range_position_mid"].fillna(0.5) >= v]))

    for v in [2, 5]:
        G.append((f"t_imp<={v}", lambda d, v=v: d[d["trend_age_impulses"].fillna(99) <= v]))

    for v in [0.5, 1.0]:
        G.append((f"sc_rng<={v}", lambda d, v=v: d[d["signal_candle_range_atr"].fillna(99) <= v]))

    for v in [0.3, 0.8]:
        G.append((f"near>={v}", lambda d, v=v: d[d["aoi_near_edge_atr"].fillna(0) >= v]))

    return G


def _apply_gates(base: pd.DataFrame, gate_str: str, gd: dict) -> pd.DataFrame:
    for g in gate_str.split("+"):
        g = g.strip()
        if g in gd:
            try:
                base = gd[g](base)
            except Exception:
                return pd.DataFrame()
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1: Top-3 SL models per cell — all 7 years
# ═══════════════════════════════════════════════════════════════════════════════
def stage_1(df: pd.DataFrame) -> dict:
    print("\n" + "=" * 80)
    print("STAGE 1: Top-3 SL per cell — all 7 years")
    print("=" * 80)

    cells: dict = {}
    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key = f"{grp}|{dirn[:4]}"
            base     = df[(df["group"] == grp) & (df["direction"] == dirn)]
            if len(base) < MIN_N_CELL:
                continue

            sl_results: list[tuple] = []
            for sl in sorted(df["sl_model"].unique()):
                sub   = base[base["sl_model"] == sl]
                m     = M(sub, N_YEARS)
                score = m["contribution"] if m["exp"] > 0 else m["exp"] * 100
                sl_results.append((sl, m, score))

            sl_results.sort(key=lambda x: x[2], reverse=True)
            top3 = [r[0] for r in sl_results[:3]]
            cells[cell_key] = {"group": grp, "dir": dirn, "sl_models": top3}

            print(f"\n  {cell_key}:")
            for sl, m, _ in sl_results[:5]:
                marker = " <-" if sl in top3 else ""
                print(f"    {sl:>30} | {m['n']:>4} | {m['tpy']:>5.1f} tpy | "
                      f"{m['win']:>5.1f}% | {m['exp']:>7.4f} | "
                      f"contrib {m['contribution']:>6.2f}{marker}")
    return cells


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2: Gate sweep depth 0-2 — all 7 years, sensitivity filter
# ═══════════════════════════════════════════════════════════════════════════════
def stage_2(df: pd.DataFrame, cells: dict) -> list[dict]:
    print("\n" + "=" * 80)
    print("STAGE 2: Gate sweep depth 0-2 | sensitivity filter | all 7 years")
    print("=" * 80)

    all_configs: list[dict] = []

    for cell_key, cell_info in cells.items():
        grp, dirn = cell_info["group"], cell_info["dir"]
        gates     = gate_lib(dirn)
        gates_d   = dict(gates)

        # Cell-level baseline win% for suspicion penalty (across all SL models)
        cell_base     = df[(df["group"] == grp) & (df["direction"] == dirn)]
        cell_base_win = 100.0 * cell_base["win"].sum() / len(cell_base) if len(cell_base) > 0 else 0.0

        for sl in cell_info["sl_models"]:
            base   = df[
                (df["group"] == grp)
                & (df["direction"] == dirn)
                & (df["sl_model"] == sl)
            ]
            base_m = M(base, N_YEARS)

            # Depth-0 baseline
            all_configs.append({
                "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                "gates": "none", "depth": 0, **base_m,
            })

            # Depth-1: track all gate exps for sensitivity check
            gate_exp: dict[str, float] = {}
            passing_singles: list[str] = []

            for gname, gfn in gates:
                try:
                    filt = gfn(base)
                except Exception:
                    continue
                gate_exp[gname] = float(filt["return_r"].mean()) if len(filt) > 0 else -999.0
                m = M(filt, N_YEARS)
                if m["n"] < MIN_N_CELL or m["tpy"] < MIN_TPY_CELL:
                    continue
                if m["exp"] <= base_m["exp"]:
                    continue
                all_configs.append({
                    "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                    "gates": gname, "depth": 1, **m,
                })
                passing_singles.append(gname)

            # Sensitivity filter: only sensitive singles enter depth-2 combos
            sensitive_singles = [
                g for g in passing_singles
                if _gate_is_sensitive(g, gate_exp, base_m["exp"])
            ]
            isolated = [g for g in passing_singles if g not in sensitive_singles]
            if isolated:
                print(f"    [{cell_key}|{sl}] isolated gates (skip combos): {isolated}")

            # Depth-2: combos from sensitive singles only
            for g1, g2 in combinations(sensitive_singles[:14], 2):
                if g1 not in gates_d or g2 not in gates_d:
                    continue
                try:
                    f = gates_d[g2](gates_d[g1](base))
                except Exception:
                    continue
                m = M(f, N_YEARS)
                if m["n"] < MIN_N_CELL or m["tpy"] < MIN_TPY_CELL:
                    continue
                if m["exp"] <= base_m["exp"]:
                    continue
                all_configs.append({
                    "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                    "gates": f"{g1}+{g2}", "depth": 2, **m,
                })

        # Annotate adj_contrib: depth penalty + suspicion penalty for high-win outliers
        cell_cfgs = [c for c in all_configs if c["cell"] == cell_key]
        for c in cell_cfgs:
            c["adj_contrib"] = _adj_contrib(c, cell_base_win, c["depth"])

        cell_cfgs.sort(key=lambda x: x["adj_contrib"], reverse=True)
        print(f"\n  {cell_key} ({len(cell_cfgs)} configs):")
        for c in cell_cfgs[:6]:
            print(f"    {c['sl']:>30} | {c['gates']:>45} | d{c['depth']} | "
                  f"{c['tpy']:>5.1f} tpy | {c['win']:>5.1f}% | "
                  f"{c['exp']:>7.4f} | adj_c {c['adj_contrib']:>6.2f}")

    return all_configs


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3: Nested 7-fold LOO — gate selected on 6-year train, tested on holdout
# ═══════════════════════════════════════════════════════════════════════════════
def stage_3(df: pd.DataFrame, cells: dict, all_configs: list[dict]) -> list[dict]:
    print("\n" + "=" * 80)
    print("STAGE 3: Nested 7-fold LOO — gate selected on 6 years, tested on held-out year")
    print(f"         exp > 0 + n >= {LOO_MIN_FOLD_N} on held-out year | "
          f"Primary: {LOO_MIN_PASS}/7 | Fallback: {LOO_FALLBACK_PASS}/7 + TPY >= {LOO_FALLBACK_TPY}")
    print("=" * 80)

    loo_configs: list[dict] = []

    for cell_key, cell_info in cells.items():
        grp, dirn = cell_info["group"], cell_info["dir"]
        gates     = gate_lib(dirn)
        gates_d   = dict(gates)

        for sl in cell_info["sl_models"]:
            base = df[
                (df["group"] == grp)
                & (df["direction"] == dirn)
                & (df["sl_model"] == sl)
            ]
            if len(base) < MIN_N_CELL:
                continue

            loo_pass   = 0
            yr_details: list[dict] = []

            for hold_yr in ALL_YEARS:
                train_df   = base[base["year"] != hold_yr]
                test_df    = base[base["year"] == hold_yr]
                train_span = N_YEARS - 1  # 6 years

                baseline_train = M(train_df, train_span)

                # Cell-level baseline win% on train set (for suspicion penalty)
                cell_train = df[
                    (df["group"] == grp)
                    & (df["direction"] == dirn)
                    & (df["year"] != hold_yr)
                ]
                cell_base_win_train = (
                    100.0 * cell_train["win"].sum() / len(cell_train)
                    if len(cell_train) > 0 else 0.0
                )

                # ── Gate scoring on train set (mirrors Stage 2) ───────────────
                gate_exp_train: dict[str, float] = {}
                passing_singles: list[str]       = []

                for gname, gfn in gates:
                    try:
                        filt = gfn(train_df)
                    except Exception:
                        continue
                    gate_exp_train[gname] = (
                        float(filt["return_r"].mean()) if len(filt) > 0 else -999.0
                    )
                    m = M(filt, train_span)
                    if m["n"] < MIN_N_CELL or m["tpy"] < MIN_TPY_CELL:
                        continue
                    if m["exp"] <= baseline_train["exp"]:
                        continue
                    passing_singles.append(gname)

                sensitive_singles = [
                    g for g in passing_singles
                    if _gate_is_sensitive(g, gate_exp_train, baseline_train["exp"])
                ]

                # ── Select best gate by adj_contrib on train ──────────────────
                best_gate = "none"
                best_adj  = _adj_contrib(baseline_train, cell_base_win_train, 0)

                for gname in passing_singles:
                    if gname not in gates_d:
                        continue
                    try:
                        filt = gates_d[gname](train_df)
                    except Exception:
                        continue
                    adj = _adj_contrib(M(filt, train_span), cell_base_win_train, 1)
                    if adj > best_adj:
                        best_gate = gname
                        best_adj  = adj

                for g1, g2 in combinations(sensitive_singles[:14], 2):
                    if g1 not in gates_d or g2 not in gates_d:
                        continue
                    try:
                        f = gates_d[g2](gates_d[g1](train_df))
                    except Exception:
                        continue
                    m_g = M(f, train_span)
                    if m_g["n"] < MIN_N_CELL or m_g["tpy"] < MIN_TPY_CELL:
                        continue
                    if m_g["exp"] <= baseline_train["exp"]:
                        continue
                    adj = _adj_contrib(m_g, cell_base_win_train, 2)
                    if adj > best_adj:
                        best_gate = f"{g1}+{g2}"
                        best_adj  = adj

                # ── Apply best gate (trained on 6 years) to held-out year ─────
                test_filtered = (
                    _apply_gates(test_df, best_gate, gates_d)
                    if best_gate != "none" else test_df
                )
                ym = M(test_filtered, 1, str(hold_yr))
                yr_details.append({**ym, "gate_selected": best_gate})

                if ym["n"] >= LOO_MIN_FOLD_N and ym["exp"] > 0:
                    loo_pass += 1

            # ── Attach loo_pass to the Stage-2 best config for this (cell, SL) ─
            s2_cfgs = [c for c in all_configs if c["cell"] == cell_key and c["sl"] == sl]
            if not s2_cfgs:
                continue
            best_s2 = max(s2_cfgs, key=lambda x: x.get("adj_contrib", x["contribution"]))
            loo_configs.append({**best_s2, "loo_pass": loo_pass, "yr_details": yr_details})

    loo_configs.sort(
        key=lambda x: (x["loo_pass"], x.get("adj_contrib", x["contribution"])),
        reverse=True,
    )

    for cell_key in sorted({c["cell"] for c in loo_configs}):
        primary  = [c for c in loo_configs if c["cell"] == cell_key
                    and c["loo_pass"] >= LOO_MIN_PASS]
        fallback = [c for c in loo_configs if c["cell"] == cell_key
                    and c["loo_pass"] >= LOO_FALLBACK_PASS
                    and c["tpy"] >= LOO_FALLBACK_TPY]
        print(f"\n  {cell_key}: {len(primary)} primary ({LOO_MIN_PASS}/7) | "
              f"{len(fallback)} at fallback level ({LOO_FALLBACK_PASS}/7)")
        primary.sort(key=lambda x: x.get("adj_contrib", x["contribution"]), reverse=True)
        for c in primary[:4]:
            yr_markers = " ".join(
                "+" if (y["exp"] > 0 and y["n"] >= LOO_MIN_FOLD_N)
                else ("-" if y["n"] >= LOO_MIN_FOLD_N else "?")
                for y in c["yr_details"]
            )
            gates_per_fold = " | ".join(y["gate_selected"] for y in c["yr_details"])
            print(f"    d{c['depth']} | {c['gates']:>45} | {c['tpy']:>5.1f} tpy | "
                  f"{c['win']:>5.1f}% | {c['exp']:>7.4f} | LOO {c['loo_pass']}/7 | [{yr_markers}]")
            print(f"         gates/fold: {gates_per_fold}")

    return loo_configs


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4: Portfolio Assembly — all 7 years must each have >= 100 trades + exp > 0
# ═══════════════════════════════════════════════════════════════════════════════
def stage_4(df: pd.DataFrame, loo_configs: list[dict]) -> dict:
    print("\n" + "=" * 80)
    print("STAGE 4: Portfolio Assembly — combinatorial search")
    print(f"         Every year >= {MIN_PORT_TRADES_PER_YR} trades | exp > 0 | "
          f"win >= {PORT_WIN_PER_YEAR}% | avg TPY >= {MIN_PORT_TPY}")
    print("=" * 80)

    gates_cache: dict = {}

    # Primary: LOO >= 6/7. Fallback for cells with zero primary configs.
    cell_options: dict = defaultdict(list)
    for c in loo_configs:
        if c["loo_pass"] >= LOO_MIN_PASS and c["exp"] > 0:
            cell_options[c["cell"]].append(c)

    fallback_cells: list[str] = []
    for c in loo_configs:
        if (c["cell"] not in cell_options
                and c["loo_pass"] >= LOO_FALLBACK_PASS
                and c["exp"] > 0
                and c["tpy"] >= LOO_FALLBACK_TPY):
            cell_options[c["cell"]].append(c)
            if c["cell"] not in fallback_cells:
                fallback_cells.append(c["cell"])

    if fallback_cells:
        print(f"\n  LOO fallback ({LOO_FALLBACK_PASS}/7) cells: {fallback_cells}")

    for k in cell_options:
        cell_options[k].sort(
            key=lambda x: x["exp"] * DEPTH_PENALTY.get(x["depth"], 0.5),
            reverse=True,
        )

    print(f"\nCells with valid configs: {sorted(cell_options.keys())}")
    for cell, opts in sorted(cell_options.items()):
        print(f"  {cell}: {len(opts)} valid")
        for c in opts[:3]:
            print(f"    {c['sl']:>30} | {c['gates']:>45} | "
                  f"{c['tpy']:>5.1f} tpy | {c['win']:>5.1f}% | {c['exp']:>7.4f} | "
                  f"LOO {c['loo_pass']}/7")

    # Top-3 diverse configs per cell: best exp, best win%, best contribution
    # TPY floor of 18: prevents high-win / low-volume outliers from dominating
    TPY_FLOOR = 18
    cell_top3: dict = {}
    for k, opts in cell_options.items():
        candidates: list[dict] = []
        seen: set = set()
        for key_fn in [
            lambda lst: sorted([o for o in lst if o["tpy"] >= TPY_FLOOR],
                               key=lambda x: x["exp"], reverse=True),
            lambda lst: sorted([o for o in lst if o["tpy"] >= TPY_FLOOR],
                               key=lambda x: x["win"], reverse=True),
            lambda lst: sorted([o for o in lst if o["tpy"] >= TPY_FLOOR],
                               key=lambda x: x["contribution"], reverse=True),
        ]:
            for o in key_fn(opts):
                k2 = (o["sl"], o["gates"])
                if k2 not in seen:
                    candidates.append(o)
                    seen.add(k2)
                    break
        cell_top3[k] = candidates if candidates else ([opts[0]] if opts else [])

    # Pre-compute per-cell aggregate stats for ALL 7 years
    print("\n  Pre-computing cell stats (all 7 years) ...")
    cell_stats: dict = {}

    for cell_key, cfgs in cell_top3.items():
        for ci, cfg in enumerate(cfgs):
            grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
            base = df[
                (df["group"] == grp)
                & (df["direction"] == dirn)
                & (df["sl_model"] == sl)
            ]
            if cfg["gates"] != "none":
                if dirn not in gates_cache:
                    gates_cache[dirn] = dict(gate_lib(dirn))
                base = _apply_gates(base, cfg["gates"], gates_cache[dirn])

            n      = len(base)
            n_wins = int(base["win"].sum()) if n > 0 else 0
            sum_r  = float(base["return_r"].sum()) if n > 0 else 0.0
            gp     = float(base.loc[base["return_r"] > 0, "return_r"].sum()) if n > 0 else 0.0
            gl     = float(abs(base.loc[base["return_r"] < 0, "return_r"].sum())) if n > 0 else 0.0

            yr_stats: dict = {}
            for yr in ALL_YEARS:
                yd = base[base["year"] == yr]
                yn = len(yd)
                yr_stats[yr] = {
                    "n":      yn,
                    "n_wins": int(yd["win"].sum()) if yn > 0 else 0,
                    "sum_r":  float(yd["return_r"].sum()) if yn > 0 else 0.0,
                }
            cell_stats[(cell_key, ci)] = {
                "n": n, "n_wins": n_wins, "sum_r": sum_r,
                "gp": gp, "gl": gl, "yr": yr_stats,
            }

    # Combinatorial search
    cells_list     = sorted(cell_top3.keys())
    options_w_skip = [list(range(len(cell_top3[k]))) + [-1] for k in cells_list]
    n_combos       = int(np.prod([len(o) for o in options_w_skip]))
    print(f"\n  Search: {len(cells_list)} cells × "
          f"{[len(o) for o in options_w_skip]} opts = {n_combos} combos")

    best_portfolios: list[dict] = []

    for combo in product(*options_w_skip):
        total_n = total_wins = skipped = 0
        total_r = total_gp = total_gl  = 0.0
        port: dict = {}

        for i, ci in enumerate(combo):
            if ci == -1:
                skipped += 1
                continue
            ck = cells_list[i]
            st = cell_stats[(ck, ci)]
            total_n    += st["n"]
            total_wins += st["n_wins"]
            total_r    += st["sum_r"]
            total_gp   += st["gp"]
            total_gl   += st["gl"]
            port[ck]    = ci

        if not port or skipped > MAX_SKIPPED_CELLS:
            continue

        tpy = total_n / N_YEARS
        if tpy < MIN_PORT_TPY:
            continue

        win_pct = 100.0 * total_wins / total_n if total_n > 0 else 0.0
        exp_r   = total_r / total_n if total_n > 0 else 0.0
        pf      = total_gp / total_gl if total_gl > 0 else 99.0

        if exp_r <= 0 or win_pct < MIN_PORT_WIN:
            continue

        # Hard constraint: ALL 7 years must have >= MIN_PORT_TRADES_PER_YR AND exp > 0
        valid = True
        for yr in ALL_YEARS:
            yr_r = yr_n = 0
            for i, ci in enumerate(combo):
                if ci == -1:
                    continue
                ck  = cells_list[i]
                ys  = cell_stats[(ck, ci)]["yr"].get(yr, {"n": 0, "sum_r": 0.0})
                yr_r += ys["sum_r"]
                yr_n += ys["n"]
            if yr_n < MIN_PORT_TRADES_PER_YR:
                valid = False
                break
            if yr_r / yr_n <= 0:
                valid = False
                break
            yr_wins = sum(
                cell_stats[(cells_list[i], ci)]["yr"].get(yr, {"n_wins": 0})["n_wins"]
                for i, ci in enumerate(combo) if ci != -1
            )
            if 100.0 * yr_wins / yr_n < PORT_WIN_PER_YEAR:
                valid = False
                break

        if not valid:
            continue

        score = (win_pct - BREAKEVEN) * np.sqrt(tpy) * pf
        best_portfolios.append({
            "combo": combo, "port_idx": port, "n_cells": len(port),
            "skipped": skipped, "n": total_n, "tpy": round(tpy, 1),
            "win": round(win_pct, 2), "exp": round(exp_r, 4),
            "pf": round(pf, 3), "score": round(score, 1),
        })

    best_portfolios.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n  {len(best_portfolios)} portfolios pass all constraints")

    def idx_to_port(bp: dict) -> dict:
        return {ck: cell_top3[ck][ci] for ck, ci in bp["port_idx"].items()}

    if best_portfolios:
        print("\nTop 15 portfolios:")
        for i, bp in enumerate(best_portfolios[:15]):
            print(f"  #{i+1:2d}: {bp['n_cells']} cells | {bp['tpy']:>6.1f} TPY | "
                  f"{bp['win']:>5.1f}% win | {bp['exp']:>6.4f} exp | "
                  f"PF {bp['pf']:>5.3f} | score {bp['score']}")

        for rank in range(min(3, len(best_portfolios))):
            bp   = best_portfolios[rank]
            port = idx_to_port(bp)
            print(f"\n  == Portfolio #{rank + 1} ==")
            _print_portfolio(port, df, f"Rank-{rank + 1}")

    result: dict = {}
    for i, bp in enumerate(best_portfolios[:5]):
        result[f"rank{i + 1}"] = idx_to_port(bp)
    return result


def _print_portfolio(port: dict, df: pd.DataFrame, name: str) -> None:
    gates_cache: dict = {}
    frames: list[pd.DataFrame] = []
    print(f"\n  Portfolio: {name}")

    for cell_key in sorted(port.keys()):
        cfg = port[cell_key]
        grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
        base = df[
            (df["group"] == grp)
            & (df["direction"] == dirn)
            & (df["sl_model"] == sl)
        ]
        if cfg["gates"] != "none":
            if dirn not in gates_cache:
                gates_cache[dirn] = dict(gate_lib(dirn))
            base = _apply_gates(base, cfg["gates"], gates_cache[dirn])

        m = M(base, N_YEARS)
        frames.append(base)
        print(f"    {cell_key:>10} | {sl:>30} | {cfg['gates']:>45} | "
              f"{m['tpy']:>5.1f} tpy | {m['win']:>5.1f}% | {m['exp']:>7.4f} | "
              f"LOO {cfg.get('loo_pass', '?')}/7")

    if not frames:
        return

    full    = pd.concat(frames, ignore_index=True)
    overall = M(full, N_YEARS)
    print(f"\n  TOTAL: {overall['n']} trades | {overall['tpy']} TPY | "
          f"{overall['win']:.1f}% win | {overall['exp']:.4f} exp | "
          f"PF {overall['pf']:.3f} | MLS {overall['mls']}")

    print(f"\n  Year-by-Year:")
    for yr in ALL_YEARS:
        ym     = M(full[full["year"] == yr], 1, str(yr))
        status = ("OK  " if ym["win"] >= PORT_WIN_PER_YEAR and ym["exp"] > 0
                  else ("PASS" if ym["exp"] > 0 else "LOSS"))
        print(f"    {yr}: {ym['n']:>4} trades | {ym['win']:>5.1f}% win | "
              f"{ym['exp']:>7.4f} exp | PF {ym['pf']:>6.3f} | {status}")


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 5: Final summary + CSV export
# ═══════════════════════════════════════════════════════════════════════════════
def stage_5(df: pd.DataFrame, portfolios: dict) -> None:
    print("\n" + "=" * 80)
    print("STAGE 5: Final Summary — 7-year LOO validated portfolios")
    print("=" * 80)

    gates_cache: dict = {}

    for port_name, port in portfolios.items():
        print(f"\n{'─' * 60}")
        print(f"  Portfolio: {port_name}")
        print(f"{'─' * 60}")

        all_frames: list[pd.DataFrame] = []
        for cell_key in sorted(port.keys()):
            cfg = port[cell_key]
            grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
            base = df[
                (df["group"] == grp)
                & (df["direction"] == dirn)
                & (df["sl_model"] == sl)
            ]
            if cfg["gates"] != "none":
                if dirn not in gates_cache:
                    gates_cache[dirn] = dict(gate_lib(dirn))
                base = _apply_gates(base, cfg["gates"], gates_cache[dirn])
            all_frames.append(base)

        if not all_frames:
            continue

        full = pd.concat(all_frames, ignore_index=True)
        fm   = M(full, N_YEARS)
        print(f"\n  All years: {fm['n']} trades | {fm['tpy']} TPY | "
              f"{fm['win']:.1f}% win | {fm['exp']:.4f} exp | "
              f"PF {fm['pf']:.3f} | MLS {fm['mls']}")

        print(f"\n  Year-by-Year:")
        for yr in ALL_YEARS:
            ym     = M(full[full["year"] == yr], 1, str(yr))
            status = ("OK  " if ym["win"] >= PORT_WIN_PER_YEAR and ym["exp"] > 0
                      else ("PASS" if ym["exp"] > 0 else "LOSS"))
            print(f"    {yr}: {ym['n']:>4} trades | {ym['win']:>5.1f}% win | "
                  f"{ym['exp']:>7.4f} exp | PF {ym['pf']:>6.3f} | {status}")

    out  = Path(__file__).parent / "robust_configs_v5.csv"
    rows: list[dict] = []
    for port_name, port in portfolios.items():
        for cell_key, cfg in port.items():
            rows.append({
                "portfolio": port_name, "cell": cell_key,
                "sl": cfg["sl"], "dir": cfg["dir"], "gates": cfg["gates"],
                "depth": cfg.get("depth", 0), "tpy": cfg["tpy"],
                "win": cfg["win"], "exp": cfg["exp"],
                "loo_pass": cfg.get("loo_pass", "?"),
            })
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n  Saved -> {out}")


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    df = load_data()
    print(f"\n{len(df)} rows | {df['id'].nunique()} signals | {N_YEARS} years: {ALL_YEARS}")
    print(f"SL models: {sorted(df['sl_model'].unique())}")
    print(f"LOO: {LOO_MIN_PASS}/7 primary | exp > 0 per fold | "
          f"n >= {LOO_MIN_FOLD_N} per fold | no benefit of doubt")
    print(f"Portfolio: avg TPY >= {MIN_PORT_TPY} | every year >= {MIN_PORT_TRADES_PER_YR} trades | "
          f"every year exp > 0 + win >= {PORT_WIN_PER_YEAR}% | overall win >= {MIN_PORT_WIN}%")

    cells      = stage_1(df)
    configs    = stage_2(df, cells)
    loo_cfgs   = stage_3(df, cells, configs)
    portfolios = stage_4(df, loo_cfgs)
    stage_5(df, portfolios)

    print("\nDone.")


if __name__ == "__main__":
    main()
