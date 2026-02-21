#!/usr/bin/env python3
"""
Export signals.csv and exit_simulations.csv for system configuration analysis.

Fixed filters applied:
  - entry_signal.is_break_candle_last = TRUE
  - entry_signal.sl_model_version     = 'CHECK_GEO'

NO post-trade flags (is_bad_pre48) are applied.

Usage:
    cd data-retriever
    python export_analysis_data.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2

import core.env  # noqa: F401
from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

OUT_DIR = Path(__file__).parent / "analysis"

_SIGNALS_SQL = """\
SELECT
    es.id,
    es.signal_time,
    es.symbol,
    es.direction,
    es.trend_alignment_strength,
    es.aoi_classification,
    es.conflicted_tf,
    es.hour_of_day_utc,
    es.aoi_touch_count_since_creation,
    es.max_retest_penetration_atr,
    es.bars_between_retest_and_break,
    pec.htf_range_position_mid,
    pec.htf_range_position_high,
    pec.distance_to_next_htf_obstacle_atr,
    pec.session_directional_bias,
    pec.break_close_location,
    pec.break_impulse_range_atr,
    pec.break_impulse_body_atr,
    pec.retest_candle_body_penetration,
    pec.aoi_last_reaction_strength,
    pec.recent_trend_payoff_atr_24h,
    pec.recent_trend_payoff_atr_48h,
    pec.trend_age_bars_1h,
    pec.trend_age_impulses,
    pec.aoi_height_atr,
    pec.distance_from_last_impulse_atr,
    pec.aoi_time_since_last_touch,
    pec.htf_range_size_mid_atr,
    pec.htf_range_size_high_atr,
    pec.aoi_midpoint_range_position_mid,
    pec.aoi_midpoint_range_position_high,
    sg.aoi_far_edge_atr,
    sg.aoi_near_edge_atr,
    sg.aoi_height_atr                   AS geo_aoi_height_atr,
    sg.signal_candle_opposite_extreme_atr,
    sg.signal_candle_range_atr,
    sg.signal_candle_body_atr
FROM trenda_replay.entry_signal          es
JOIN trenda_replay.pre_entry_context_v2  pec ON pec.entry_signal_id = es.id
JOIN trenda_replay.sl_geometry_unbiased  sg  ON sg.entry_signal_id  = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
ORDER BY es.signal_time
"""

_EXIT_SIM_SQL = """\
SELECT
    esi.entry_signal_id,
    esi.sl_model,
    esi.rr_multiple,
    esi.sl_atr,
    esi.exit_reason,
    esi.return_r,
    esi.bars_to_tp_hit,
    esi.bars_to_sl_hit,
    esi.exit_bar
FROM trenda_replay.exit_simulation_unbiased esi
WHERE esi.entry_signal_id IN (
    SELECT id
    FROM trenda_replay.entry_signal
    WHERE is_break_candle_last = TRUE
      AND sl_model_version     = 'CHECK_GEO'
)
ORDER BY esi.entry_signal_id, esi.sl_model, esi.rr_multiple
"""


def _connect() -> psycopg2.extensions.connection:
    cfg = {k: v for k, v in POSTGRES_DB.items() if k != "options"}
    cfg["options"] = "-c search_path=trenda_replay,public"
    return psycopg2.connect(**cfg)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        logger.info("Exporting signals …")
        signals = pd.read_sql_query(_SIGNALS_SQL, conn)
        out = OUT_DIR / "signals.csv"
        signals.to_csv(out, index=False)
        logger.info("signals.csv → %d rows → %s", len(signals), out)

        logger.info("Exporting exit simulations …")
        exits = pd.read_sql_query(_EXIT_SIM_SQL, conn)
        out = OUT_DIR / "exit_simulations.csv"
        exits.to_csv(out, index=False)
        logger.info("exit_simulations.csv → %d rows → %s", len(exits), out)


if __name__ == "__main__":
    main()
