"""
Backfill Unbiased Exit Simulations

Goal:
Generate a fresh set of exit simulations that are strictly bias-free.

Methodology:
1. Identify Signal Candle (T) using signal_time.
2. Calculate SL/TP Geometry using OHLC of T.
3. Use Close of T as the Entry Price.
4. Price Path starts at T+1 (exactly one bar after signal).
5. Simulate 72 bars (T+1 to T+72).
6. Store Result: `exit_simulation_unbiased`.
"""

import sys
import os
from datetime import timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from dataclasses import dataclass

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.executor import DBExecutor
from externals.data_fetcher import fetch_data
from replay.sl_geometry import SLGeometryCalculator
from replay.exit_simulator import ExitSimulator
from replay.path_extremes import PathExtremesCalculator, PathExtremeRow
from replay.config import SCHEMA_NAME, SL_MODELS, RR_MULTIPLES
from models import TrendDirection

# Filtered Query (Targeted to 417249 for initial run)
FETCH_SIGNALS_SQL = f"""
    SELECT 
        es.id, 
        es.symbol, 
        es.signal_time, 
        es.direction, 
        es.entry_price, 
        es.atr_1h,
        es.aoi_low, 
        es.aoi_high
    FROM {SCHEMA_NAME}.entry_signal es
    WHERE es.is_break_candle_last = FALSE
    AND es.sl_model_version = 'CHECK_GEO'
    ORDER BY es.signal_time ASC
"""

INSERT_UNBIASED_SIM_SQL = f"""
    INSERT INTO {SCHEMA_NAME}.exit_simulation_unbiased (
        entry_signal_id,
        sl_model, rr_multiple, sl_atr, tp_atr,
        exit_reason, exit_bar, return_atr, return_r,
        mfe_atr, mae_atr, bars_to_sl_hit, bars_to_tp_hit, is_bad_pre48
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (entry_signal_id, sl_model, rr_multiple) DO UPDATE SET
        sl_atr = EXCLUDED.sl_atr,
        tp_atr = EXCLUDED.tp_atr,
        exit_reason = EXCLUDED.exit_reason,
        exit_bar = EXCLUDED.exit_bar,
        return_atr = EXCLUDED.return_atr,
        return_r = EXCLUDED.return_r,
        mfe_atr = EXCLUDED.mfe_atr,
        mae_atr = EXCLUDED.mae_atr,
        bars_to_sl_hit = EXCLUDED.bars_to_sl_hit,
        bars_to_tp_hit = EXCLUDED.bars_to_tp_hit,
        is_bad_pre48 = EXCLUDED.is_bad_pre48,
        created_at = CURRENT_TIMESTAMP
"""

INSERT_UNBIASED_GEOMETRY_SQL = f"""
    INSERT INTO {SCHEMA_NAME}.sl_geometry_unbiased (
        entry_signal_id, direction,
        aoi_far_edge_atr, aoi_near_edge_atr, aoi_height_atr, aoi_age_bars,
        signal_candle_opposite_extreme_atr, signal_candle_range_atr, signal_candle_body_atr,
        lookahead_drift_atr
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id) DO UPDATE SET
        aoi_far_edge_atr = EXCLUDED.aoi_far_edge_atr,
        aoi_near_edge_atr = EXCLUDED.aoi_near_edge_atr,
        aoi_height_atr = EXCLUDED.aoi_height_atr,
        aoi_age_bars = EXCLUDED.aoi_age_bars,
        signal_candle_opposite_extreme_atr = EXCLUDED.signal_candle_opposite_extreme_atr,
        signal_candle_range_atr = EXCLUDED.signal_candle_range_atr,
        signal_candle_body_atr = EXCLUDED.signal_candle_body_atr,
        lookahead_drift_atr = EXCLUDED.lookahead_drift_atr,
        created_at = CURRENT_TIMESTAMP
"""


@dataclass
class SimulationStats:
    total_signals: int = 0
    signals_processed: int = 0
    total_sims: int = 0
    # Granular skips
    skip_no_data: int = 0
    skip_time_match: int = 0
    skip_invalid_geo: int = 0
    skip_no_future: int = 0

def backfill_unbiased_simulations():
    print("Fetching qualifying signals for Unbiased Simulation...", flush=True)
    rows = DBExecutor.fetch_all(FETCH_SIGNALS_SQL, context="backfill_fetch")
    
    if not rows:
        print("No signals found.", flush=True)
        return

    stats = SimulationStats()
    stats.total_signals = len(rows)
    print(f"Found {stats.total_signals} signals to process.", flush=True)
    
    for i, row in enumerate(rows):
        process_signal(row, stats)
        
        if (i + 1) % 50 == 0:
            print(f"Progress: {i + 1}/{stats.total_signals} signals processed...", flush=True)
            
    print(f"Unbiased simulation complete.\n")
    print(f"Total Found: {stats.total_signals}")
    print(f"Processed:   {stats.signals_processed}")
    print(f"Skipped Details:")
    print(f"  - No Data from MT5:        {stats.skip_no_data}")
    print(f"  - Signal Time Not Found:   {stats.skip_time_match}")
    print(f"  - Invalid Geo Calculation: {stats.skip_invalid_geo}")
    print(f"  - No Future Bars Found:    {stats.skip_no_future}")

def process_signal(row, stats):
    signal_id = row[0]
    symbol = row[1]
    signal_time_db = row[2]
    direction_str = row[3]
    entry_price = float(row[4])
    atr_1h = float(row[5])
    aoi_low = float(row[6])
    aoi_high = float(row[7])
    
    direction = TrendDirection.from_raw(direction_str)
    
    # 1. UTC Conversion for consistency
    if signal_time_db.tzinfo is None:
        signal_time_utc = signal_time_db.replace(tzinfo=timezone.utc)
    else:
        signal_time_utc = signal_time_db.astimezone(timezone.utc)

    # 2. Fetch Data (Lookback 1000, Lookforward 120h)
    # Increasing lookback to 1000 helps force MT5 to download more history.
    end_time = signal_time_utc + timedelta(hours=120)
    candles = fetch_data(symbol, 16385, lookback=1000, end_date=end_time)
    
    if candles is None or candles.empty:
        stats.skip_no_data += 1
        return

    candles['time'] = pd.to_datetime(candles['time'], utc=True)
    candles.set_index('time', inplace=True)
    
    # Identify Signal Candle (T)
    if signal_time_utc not in candles.index:
        stats.skip_time_match += 1
        return
    
    signal_candle = candles.loc[signal_time_utc]
    
    # 3. Calculate SL Geometry using Signal Candle (T)
    signal_candle_dict = {
        "open": float(signal_candle['open']),
        "high": float(signal_candle['high']),
        "low": float(signal_candle['low']),
        "close": float(signal_candle['close']),
    }
    
    geo_calc = SLGeometryCalculator(
        entry_price=entry_price,
        atr_at_entry=atr_1h,
        direction=direction,
        aoi_low=aoi_low,
        aoi_high=aoi_high,
        signal_candle=signal_candle_dict,
        signal_time=signal_time_utc
    )
    geometry = geo_calc.compute()
    if not geometry:
        stats.skip_invalid_geo += 1
        return

    # 4. Simulation Path starts at T+1
    valid_candles = candles[candles.index > signal_time_utc]
    if valid_candles.empty:
        stats.skip_no_future += 1
        return

    # Use whatever we have, up to 72 bars
    actual_future_bars = len(valid_candles)
    sim_candles = valid_candles.iloc[:min(72, actual_future_bars)]
    
    if actual_future_bars < 72:
        # Just a log to know we are dealing with a partial path
        pass 
    
    path_rows = []
    running_mfe = float('-inf')
    running_mae = float('inf')
    
    for bar_idx, (cur_time, c) in enumerate(sim_candles.iterrows(), start=1):
        c_close = float(c['close'])
        c_high = float(c['high'])
        c_low = float(c['low'])
        
        if direction == TrendDirection.BULLISH:
            ret = (c_close - entry_price) / atr_1h
            imax_mfe = (c_high - entry_price) / atr_1h
            imax_mae = (c_low - entry_price) / atr_1h
        else:
            ret = (entry_price - c_close) / atr_1h
            imax_mfe = (entry_price - c_low) / atr_1h
            imax_mae = (entry_price - c_high) / atr_1h
            
        running_mfe = max(running_mfe, ret)
        running_mae = min(running_mae, ret)
        
        path_rows.append(PathExtremeRow(
            bar_index=bar_idx,
            return_atr_at_bar=ret,
            mfe_atr_to_here=running_mfe,
            mae_atr_to_here=running_mae,
            mfe_atr_high_low=max(running_mfe, imax_mfe),
            mae_atr_high_low=min(running_mae, imax_mae)
        ))

    stats.signals_processed += 1
    
    # 5. Persist Unbiased Geometry
    DBExecutor.execute_non_query(
        INSERT_UNBIASED_GEOMETRY_SQL,
        (
            signal_id, geometry.direction,
            geometry.aoi_far_edge_atr, geometry.aoi_near_edge_atr,
            geometry.aoi_height_atr, geometry.aoi_age_bars,
            geometry.signal_candle_opposite_extreme_atr,
            geometry.signal_candle_range_atr,
            geometry.signal_candle_body_atr,
            geometry.lookahead_drift_atr
        ),
        context="insert_unbiased_geometry"
    )
    
    # 6. Run Exit Simulator
    sim = ExitSimulator(geometry, path_extremes=path_rows)
    all_sims = sim.simulate_all()
    
    for res in all_sims:
        stats.total_sims += 1
        DBExecutor.execute_non_query(
            INSERT_UNBIASED_SIM_SQL,
            (
                signal_id, res.sl_model, res.rr_multiple,
                res.sl_atr, res.tp_atr,
                res.exit_reason, res.exit_bar,
                res.return_atr, res.return_r,
                res.mfe_atr, res.mae_atr,
                res.bars_to_sl_hit, res.bars_to_tp_hit,
                res.is_bad_pre48
            ),
            context="insert_unbiased_sim"
        )

if __name__ == "__main__":
    backfill_unbiased_simulations()
