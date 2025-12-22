-- =============================================================================
-- Replay Schema DDL
-- =============================================================================
-- This DDL creates the trenda_replay schema for offline replay simulation.
-- Run this manually to create the schema and tables before running the replay.
--
-- Usage:
--   psql -d trenda -f replay_schema.sql
-- =============================================================================

-- Create the replay schema
CREATE SCHEMA IF NOT EXISTS trenda_replay;

-- =============================================================================
-- Entry Signal Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS trenda_replay.entry_signal (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    direction VARCHAR(10) NOT NULL,
    
    -- Trend data
    trend_4h VARCHAR(10),
    trend_1d VARCHAR(10),
    trend_1w VARCHAR(10),
    trend_alignment_strength INTEGER,
    
    -- AOI data
    aoi_timeframe VARCHAR(10),
    aoi_low NUMERIC,
    aoi_high NUMERIC,
    aoi_classification VARCHAR(20),
    
    -- Entry data
    entry_price NUMERIC,
    atr_1h NUMERIC,
    
    -- Quality score
    final_score NUMERIC,
    tier VARCHAR(20),
    is_break_candle_last BOOLEAN,
    
    -- SL/TP model versions
    sl_model_version TEXT NOT NULL,
    tp_model_version TEXT NOT NULL,
    
    -- SL distance data (renamed from aoi_raw/aoi_effective)
    aoi_structural_sl_distance_price NUMERIC,
    aoi_structural_sl_distance_atr NUMERIC,
    effective_sl_distance_price NUMERIC,
    effective_sl_distance_atr NUMERIC,
    
    -- TP distance data
    effective_tp_distance_atr NUMERIC NOT NULL,
    effective_tp_distance_price NUMERIC NOT NULL,
    
    -- Trade profile
    trade_profile TEXT,
    
    -- Processing flags
    outcome_computed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    UNIQUE(symbol, signal_time)
);

-- Index for pending outcome computation
CREATE INDEX IF NOT EXISTS idx_replay_entry_signal_pending 
ON trenda_replay.entry_signal (outcome_computed, signal_time) 
WHERE outcome_computed = FALSE;

-- =============================================================================
-- Entry Signal Score Table (detailed stage scores)
-- =============================================================================
CREATE TABLE IF NOT EXISTS trenda_replay.entry_signal_score (
    id SERIAL PRIMARY KEY,
    entry_signal_id INTEGER REFERENCES trenda_replay.entry_signal(id) ON DELETE CASCADE,
    stage_name VARCHAR(10) NOT NULL,
    raw_score NUMERIC,
    weight NUMERIC,
    weighted_score NUMERIC
);

-- Index for score lookup
CREATE INDEX IF NOT EXISTS idx_replay_entry_signal_score_signal_id 
ON trenda_replay.entry_signal_score (entry_signal_id);

-- =============================================================================
-- Signal Outcome Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS trenda_replay.signal_outcome (
    id SERIAL PRIMARY KEY,
    entry_signal_id INTEGER UNIQUE REFERENCES trenda_replay.entry_signal(id) ON DELETE CASCADE,
    
    -- Window info (168 bars = 7 days)
    window_bars INTEGER,
    
    -- MFE/MAE (in ATR units - legacy)
    mfe_atr NUMERIC,
    mae_atr NUMERIC,
    bars_to_mfe INTEGER,
    bars_to_mae INTEGER,
    first_extreme VARCHAR(20),
    
    -- Legacy SL/TP hits (kept but no longer written to)
    bars_to_aoi_sl_hit INTEGER,
    bars_to_r_1 INTEGER,
    bars_to_r_1_5 INTEGER,
    bars_to_r_2 INTEGER,
    aoi_rr_outcome VARCHAR(30),
    
    -- New outcome fields
    realized_r NUMERIC,                -- Actual R return based on exit
    exit_reason TEXT,                  -- 'TP', 'SL', or 'TIME'
    bars_to_exit INTEGER,              -- Bars from entry to exit
    mfe_r NUMERIC,                     -- MFE normalized by effective SL (in R units)
    mae_r NUMERIC,                     -- MAE normalized by effective SL (in R units)
    bars_to_tp INTEGER,                -- Bars to TP hit (or NULL)
    bars_to_sl INTEGER,                -- Bars to SL hit (or NULL)
    
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- Checkpoint Return Table (returns at each checkpoint)
-- =============================================================================
-- Stores returns at: 3h, 6h, 12h, 24h, 48h, 72h, 96h, 120h, 144h, 168h
CREATE TABLE IF NOT EXISTS trenda_replay.checkpoint_return (
    id SERIAL PRIMARY KEY,
    signal_outcome_id INTEGER REFERENCES trenda_replay.signal_outcome(id) ON DELETE CASCADE,
    bars_after INTEGER NOT NULL,      -- e.g., 3, 6, 12, 24, 48, 72, 96, 120, 144, 168
    return_atr NUMERIC NOT NULL,      -- Return in ATR units at this checkpoint
    
    UNIQUE(signal_outcome_id, bars_after)
);

-- Index for checkpoint lookup
CREATE INDEX IF NOT EXISTS idx_replay_checkpoint_return_outcome_id 
ON trenda_replay.checkpoint_return (signal_outcome_id);

-- =============================================================================
-- Pre-Entry Context Table
-- =============================================================================
-- Stores pre-entry observable facts computed at replay time, before the entry candle.
-- All metric columns are nullable for replay-safe operation.
CREATE TABLE IF NOT EXISTS trenda_replay.pre_entry_context (
    entry_signal_id INTEGER PRIMARY KEY
        REFERENCES trenda_replay.entry_signal(id) ON DELETE CASCADE,

    -- metadata (window sizes used for computation)
    lookback_bars INTEGER NOT NULL,
    impulse_bars INTEGER NOT NULL,

    -- volatility & range
    pre_atr NUMERIC,
    pre_atr_ratio NUMERIC,
    pre_range_atr NUMERIC,
    pre_range_to_atr_ratio NUMERIC,

    -- directional pressure
    pre_net_move_atr NUMERIC,
    pre_total_move_atr NUMERIC,
    pre_efficiency NUMERIC,
    pre_counter_bar_ratio NUMERIC,

    -- AOI interaction
    pre_aoi_touch_count INTEGER,
    pre_bars_in_aoi INTEGER,
    pre_last_touch_distance_atr NUMERIC,

    -- impulse / energy
    pre_impulse_net_atr NUMERIC,
    pre_impulse_efficiency NUMERIC,
    pre_large_bar_ratio NUMERIC,

    -- microstructure
    pre_overlap_ratio NUMERIC,
    pre_wick_ratio NUMERIC,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- Utility: Drop and recreate all tables (use with caution!)
-- =============================================================================
-- To reset the replay schema:
--
-- DROP SCHEMA IF EXISTS trenda_replay CASCADE;
-- Then re-run this DDL file.
-- =============================================================================