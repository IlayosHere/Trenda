#!/usr/bin/env python3
"""
compare_versions.py — Side-by-side comparison of CHECK_GEO vs LOWER_TF_CHECK.

CHECK_GEO   : exit_simulation_unbiased, sl_model_version = 'CHECK_GEO'
LOWER_TF_CHECK: exit_simulation,          sl_model_version = 'LOWER_TF_CHECK'

N_YEARS computed dynamically per dataset from actual years present.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import psycopg2
import pandas as pd

from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

GROUPS = {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}
_S2G = {s: g for g, ss in GROUPS.items() for s in ss}

_SQL_CHECK_GEO = """\
SELECT
    es.id, es.signal_time, es.symbol, es.direction,
    esi.sl_model, esi.rr_multiple, esi.exit_reason, esi.return_r
FROM trenda_replay.entry_signal             es
JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
ORDER BY es.signal_time
"""

_SQL_LOWER = """\
SELECT
    es.id, es.signal_time, es.symbol, es.direction,
    esi.sl_model, esi.rr_multiple, esi.exit_reason, esi.return_r
FROM trenda_replay.entry_signal    es
JOIN trenda_replay.exit_simulation esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'LOWER_TF_CHECK'
ORDER BY es.signal_time
"""


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"]        = df["signal_time"].dt.year
    df["group"]       = df["symbol"].map(_S2G)
    df["win"]         = (df["exit_reason"] == "TP").astype(int)
    known = df["group"].notna()
    dropped = (~known).sum()
    if dropped:
        logger.info("Dropped %d rows (unknown symbol->group)", dropped)
        df = df[known].copy()
    return df


def load_both() -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = {k: v for k, v in POSTGRES_DB.items() if k != "options"}
    cfg["options"] = "-c search_path=trenda_replay,public"
    with psycopg2.connect(**cfg) as conn:
        logger.info("Loading CHECK_GEO ...")
        geo  = _enrich(pd.read_sql_query(_SQL_CHECK_GEO, conn))
        logger.info("Loading LOWER_TF_CHECK ...")
        low  = _enrich(pd.read_sql_query(_SQL_LOWER, conn))
    logger.info("CHECK_GEO:       %d signals | years %s",
                geo["id"].nunique(), sorted(geo["year"].unique()))
    logger.info("LOWER_TF_CHECK:  %d signals | years %s",
                low["id"].nunique(), sorted(low["year"].unique()))
    return geo, low


def M(sub: pd.DataFrame, n_years: int) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "tpy": 0.0, "win": 0.0, "exp": 0.0, "pf": 0.0}
    tpy = n / n_years
    w   = 100.0 * sub["win"].sum() / n
    e   = float(sub["return_r"].mean())
    gp  = float(sub.loc[sub["return_r"] > 0, "return_r"].sum())
    gl  = float(abs(sub.loc[sub["return_r"] < 0, "return_r"].sum()))
    pf  = gp / gl if gl > 0 else 99.0
    return {"n": n, "tpy": round(tpy, 1), "win": round(w, 2),
            "exp": round(e, 4), "pf": round(pf, 3)}


def best_sl(cell_df: pd.DataFrame, rr: float, n_years: int) -> dict | None:
    """Return metrics for the SL model with highest exp at this RR (min 60 trades)."""
    rr_df = cell_df[cell_df["rr_multiple"] == rr]
    best: dict | None = None
    for sl in rr_df["sl_model"].unique():
        sub = rr_df[rr_df["sl_model"] == sl]
        if len(sub) < 60:
            continue
        m = M(sub, n_years)
        m["sl"] = sl
        if best is None or m["exp"] > best["exp"]:
            best = m
    return best


def _fmt(m: dict | None) -> str:
    if m is None:
        return f"{'—':^67}"
    marker = " <<"  if m["win"] >= 38.0  else ""
    return (f"{m['sl']:<32} | {m['win']:>5.1f}% | {m['exp']:>+7.4f} exp | "
            f"PF {m['pf']:>5.3f} | {m['tpy']:>5.1f} tpy{marker}")


def section_compare(geo: pd.DataFrame, low: pd.DataFrame, rr: float) -> None:
    geo_years = geo["year"].nunique()
    low_years = low["year"].nunique()
    be = 100.0 / (1.0 + rr)

    print(f"\n{'=' * 120}")
    print(f"  SIDE-BY-SIDE at RR {rr:.1f}  (breakeven {be:.1f}%)")
    print(f"  CHECK_GEO: {geo_years} yr  |  LOWER_TF_CHECK: {low_years} yr")
    print(f"{'=' * 120}")
    print(f"  {'cell':<12}  {'CHECK_GEO — best SL by exp':<67}  {'LOWER_TF_CHECK — best SL by exp'}")
    print(f"  {'-' * 12}  {'-' * 67}  {'-' * 67}")

    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key = f"{grp}|{dirn[:4]}"
            geo_cell = geo[(geo["group"] == grp) & (geo["direction"] == dirn)]
            low_cell = low[(low["group"] == grp) & (low["direction"] == dirn)]
            if len(geo_cell) == 0 and len(low_cell) == 0:
                continue
            g = best_sl(geo_cell, rr, geo_years)
            l = best_sl(low_cell, rr, low_years)
            print(f"  {cell_key:<12}  {_fmt(g)}  {_fmt(l)}")


def section_rr12_lower(low: pd.DataFrame) -> None:
    rr      = 1.2
    be      = 100.0 / (1.0 + rr)
    n_years = low["year"].nunique()
    sl_models = sorted(low["sl_model"].unique())

    print(f"\n{'=' * 100}")
    print(f"  LOWER_TF_CHECK — RR {rr:.1f}  (breakeven {be:.1f}%)  — all SL models per cell")
    print(f"  {n_years} years of data")
    print(f"{'=' * 100}")

    rows: list[dict] = []

    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key = f"{grp}|{dirn[:4]}"
            rr_df = low[
                (low["group"] == grp) &
                (low["direction"] == dirn) &
                (low["rr_multiple"] == rr)
            ]
            if len(rr_df) == 0:
                continue

            sl_results: list[dict] = []
            for sl in sl_models:
                sub = rr_df[rr_df["sl_model"] == sl]
                if len(sub) < 60:
                    continue
                m = M(sub, n_years)
                sl_results.append({"cell": cell_key, "sl": sl, **m})

            if not sl_results:
                continue

            sl_results.sort(key=lambda x: x["exp"], reverse=True)
            print(f"\n  {cell_key}")
            for r in sl_results:
                marker = " <<" if r["win"] >= be else (
                         " <"  if r["exp"] > 0 else "")
                print(f"    {r['sl']:<32} | {r['n']:>5} n | {r['tpy']:>5.1f} tpy | "
                      f"{r['win']:>5.1f}% win | {r['exp']:>+7.4f} exp | "
                      f"PF {r['pf']:>5.3f}{marker}")
            rows.extend(sl_results)

    # Best overall at RR 1.2
    if rows:
        top = sorted(rows, key=lambda x: x["exp"], reverse=True)[:10]
        print(f"\n  {'— TOP 10 at RR 1.2 by exp —':^100}")
        for r in top:
            print(f"    {r['cell']:<12} {r['sl']:<32} | {r['win']:>5.1f}% | "
                  f"{r['exp']:>+7.4f} exp | {r['tpy']:>5.1f} tpy")


def section_overall_best(geo: pd.DataFrame, low: pd.DataFrame) -> None:
    """All cells pooled: best SL per RR for each version, side-by-side."""
    geo_years = geo["year"].nunique()
    low_years = low["year"].nunique()
    all_rrs   = sorted(set(geo["rr_multiple"].unique()) | set(low["rr_multiple"].unique()))

    print(f"\n{'=' * 130}")
    print("  OVERALL (all cells pooled) — best SL per RR × version, sorted by exp")
    print(f"  CHECK_GEO: {geo_years} yr  |  LOWER_TF_CHECK: {low_years} yr")
    print(f"{'=' * 130}")

    rows: list[dict] = []

    for rr in all_rrs:
        be = 100.0 / (1.0 + rr)
        print(f"\n  RR {rr:.1f}  (be={be:.1f}%)")
        print(f"  {'version':<18} {'sl_model':<32} | {'n':>6} | {'tpy':>6} | "
              f"{'win%':>6} | {'exp':>8} | {'pf':>6}")
        print(f"  {'-' * 18} {'-' * 32}   {'-' * 6}   {'-' * 6}   "
              f"{'-' * 6}   {'-' * 8}   {'-' * 6}")

        for label, df, n_years in [("CHECK_GEO", geo, geo_years),
                                    ("LOWER_TF_CHECK", low, low_years)]:
            rr_df = df[df["rr_multiple"] == rr]
            if len(rr_df) == 0:
                print(f"  {label:<18} {'— no data —'}")
                continue

            sl_results: list[dict] = []
            for sl in sorted(rr_df["sl_model"].unique()):
                sub = rr_df[rr_df["sl_model"] == sl]
                if len(sub) < 100:
                    continue
                m = M(sub, n_years)
                sl_results.append({"version": label, "rr": rr, "sl": sl, **m})
                rows.append({"version": label, "rr": rr, "sl": sl, **m})

            sl_results.sort(key=lambda x: x["exp"], reverse=True)
            for r in sl_results:
                marker = " <<" if r["win"] >= be else (" <" if r["exp"] > 0 else "")
                print(f"  {r['version']:<18} {r['sl']:<32} | {r['n']:>6} | "
                      f"{r['tpy']:>6.1f} | {r['win']:>5.1f}% | "
                      f"{r['exp']:>+8.4f} | PF {r['pf']:>5.3f}{marker}")

    # Delta table: LOWER minus CHECK_GEO at common RR × best SL per version
    common_rrs = sorted(set(geo["rr_multiple"].unique()) & set(low["rr_multiple"].unique()))
    if common_rrs and rows:
        print(f"\n{'=' * 100}")
        print("  EXP DELTA (LOWER - CHECK_GEO) at best SL per version per RR")
        print(f"{'=' * 100}")
        print(f"  {'RR':>5} | {'CHECK_GEO best SL':<32} {'exp':>8} | "
              f"{'LOWER best SL':<32} {'exp':>8} | {'delta':>8}")
        print(f"  {'-'*5}   {'-'*32} {'-'*8}   {'-'*32} {'-'*8}   {'-'*8}")

        def best_for(ver: str, rr: float) -> dict | None:
            sub = [r for r in rows if r["version"] == ver and r["rr"] == rr]
            return max(sub, key=lambda x: x["exp"]) if sub else None

        for rr in common_rrs:
            g = best_for("CHECK_GEO", rr)
            l = best_for("LOWER_TF_CHECK", rr)
            g_exp  = g["exp"] if g else float("nan")
            l_exp  = l["exp"] if l else float("nan")
            delta  = l_exp - g_exp
            g_sl   = g["sl"] if g else "—"
            l_sl   = l["sl"] if l else "—"
            marker = " +" if delta > 0 else ""
            print(f"  {rr:>5.1f} | {g_sl:<32} {g_exp:>+8.4f} | "
                  f"{l_sl:<32} {l_exp:>+8.4f} | {delta:>+8.4f}{marker}")


def main() -> None:
    geo, low = load_both()

    # Print data summary
    print(f"\nCHECK_GEO:       {geo['id'].nunique()} signals | "
          f"years {sorted(geo['year'].unique())} | "
          f"RR {sorted(geo['rr_multiple'].unique())}")
    print(f"LOWER_TF_CHECK:  {low['id'].nunique()} signals | "
          f"years {sorted(low['year'].unique())} | "
          f"RR {sorted(low['rr_multiple'].unique())}")

    # Common RR values for side-by-side
    geo_rrs = set(geo["rr_multiple"].unique())
    low_rrs = set(low["rr_multiple"].unique())
    common_rrs = sorted(geo_rrs & low_rrs)

    # Overall pooled comparison — primary output
    section_overall_best(geo, low)

    print("\nDone.")


if __name__ == "__main__":
    main()
