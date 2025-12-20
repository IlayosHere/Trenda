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
    
    -- SL distance data
    aoi_sl_tolerance_atr NUMERIC,
    aoi_raw_sl_distance_price NUMERIC,
    aoi_raw_sl_distance_atr NUMERIC,
    aoi_effective_sl_distance_price NUMERIC,
    aoi_effective_sl_distance_atr NUMERIC,
    
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
    
    -- MFE/MAE
    mfe_atr NUMERIC,
    mae_atr NUMERIC,
    bars_to_mfe INTEGER,
    bars_to_mae INTEGER,
    first_extreme VARCHAR(20),
    
    -- SL/TP hits (bar number or NULL)
    bars_to_aoi_sl_hit INTEGER,
    bars_to_r_1 INTEGER,
    bars_to_r_1_5 INTEGER,
    bars_to_r_2 INTEGER,
    
    -- R:R outcome classification
    aoi_rr_outcome VARCHAR(30),
    
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
-- Utility: Drop and recreate all tables (use with caution!)
-- =============================================================================
-- To reset the replay schema:
--
-- DROP SCHEMA IF EXISTS trenda_replay CASCADE;
-- Then re-run this DDL file.
-- =============================================================================

-- SELECT ess.stage_name, avg(lt.bars_to_aoi_sl_hit)
-- FROM trenda_replay.losing_trades lt
-- JOIN trenda_replay.entry_signal_score ess ON ess.entry_signal_id = lt.id
-- WHERE EXTRACT(DOW FROM signal_time) BETWEEN 2 AND 4
-- AND EXTRACT(HOUR FROM signal_time) BETWEEN 7 AND 17
-- AND final_score > 0.5
-- GROUP BY ess.stage_name

-- SELECT lt.symbol, lt.aoi_low, lt.aoi_high, lt.signal_time,
-- 	lt.bars_to_aoi_sl_hit, lt.bars_to_r_1, lt.bars_to_r_1_5
-- FROM trenda_replay.losing_trades lt
-- WHERE EXTRACT(DOW FROM signal_time) BETWEEN 2 AND 4
-- AND EXTRACT(HOUR FROM signal_time) BETWEEN 7 AND 17
-- AND lt.aoi_rr_outcome != 'SL_BEFORE_ANY_TP'
-- AND final_score > 0.65





-