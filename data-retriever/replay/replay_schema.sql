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
    
    -- Conflicted TF (NULL if all 3 aligned, '4H'/'1D'/'1W' for the odd one out)
    conflicted_tf VARCHAR(10),
    
    -- Retest depth metrics
    max_retest_penetration_atr NUMERIC,
    bars_between_retest_and_break INTEGER,
    
    -- Session encoding
    hour_of_day_utc INTEGER,
    session_bucket VARCHAR(20),
    
    -- AOI decay
    aoi_touch_count_since_creation INTEGER,
    
    -- Trade grouping (groups break + after-break signals together)
    trade_id VARCHAR(50),
    
    -- Processing flags
    outcome_computed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    UNIQUE(symbol, signal_time, aoi_low, aoi_high,sl_model_version,tp_model_version )
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

-- Pre-Entry Context V2 Table (Market Environment)
-- =============================================================================
-- Stores market environment metrics computed at replay time, before the entry candle.
-- Captures location, maturity, regime, and space factors.
CREATE TABLE IF NOT EXISTS trenda_replay.pre_entry_context_v2 (
    entry_signal_id INTEGER PRIMARY KEY
        REFERENCES trenda_replay.entry_signal(id) ON DELETE CASCADE,

    -- HTF Range Position (where price sits within completed ranges)
    htf_range_position_daily NUMERIC,     -- (entry - daily_low) / (daily_high - daily_low)
    htf_range_position_weekly NUMERIC,    -- (entry - weekly_low) / (weekly_high - weekly_low)
    
    -- Distance to HTF Boundaries (room to move, in ATR units)
    distance_to_daily_high_atr NUMERIC,
    distance_to_daily_low_atr NUMERIC,
    distance_to_weekly_high_atr NUMERIC,
    distance_to_weekly_low_atr NUMERIC,
    distance_to_4h_high_atr NUMERIC,
    distance_to_4h_low_atr NUMERIC,
    distance_to_next_htf_obstacle_atr NUMERIC,  -- min of relevant distances based on direction
    
    -- Session Context (previous session high/low using fixed UTC windows)
    prev_session_high NUMERIC,
    prev_session_low NUMERIC,
    distance_to_prev_session_high_atr NUMERIC,
    distance_to_prev_session_low_atr NUMERIC,
    
    -- Trend Maturity
    trend_age_bars_1h INTEGER,            -- bars since trend_alignment >= 2
    trend_age_impulses INTEGER,           -- count of directional runs >= 0.8 ATR
    recent_trend_payoff_atr_24h NUMERIC,  -- (close_now - close_24h_ago) / atr
    recent_trend_payoff_atr_48h NUMERIC,  -- (close_now - close_48h_ago) / atr
    
    -- Session Directional Bias
    session_directional_bias NUMERIC,     -- (session_close - session_open) / atr
    
    -- AOI Freshness
    aoi_time_since_last_touch INTEGER,    -- bars since last AOI overlap before signal
    aoi_last_reaction_strength NUMERIC,   -- MFE in ATR after last AOI exit (NULL if fresh)
    
    -- Momentum Chase Detection
    distance_from_last_impulse_atr NUMERIC,  -- distance from last large candle close
    
    -- HTF Range Size (compressed vs expanded markets)
    htf_range_size_daily_atr NUMERIC,        -- (max(high) - min(low)) / atr over last 20 daily candles
    htf_range_size_weekly_atr NUMERIC,       -- (max(high) - min(low)) / atr over last 12 weekly candles
    
    -- AOI Position Inside HTF Range
    aoi_midpoint_range_position_daily NUMERIC,   -- (aoi_mid - range_low) / (range_high - range_low)
    aoi_midpoint_range_position_weekly NUMERIC,  -- same for weekly
    
    -- Break Candle Metrics
    break_impulse_range_atr NUMERIC,            -- (high - low) / atr_1h
    break_impulse_body_atr NUMERIC,             -- abs(close - open) / atr_1h
    break_close_location NUMERIC,               -- bullish: (close-low)/(high-low), bearish: (high-close)/(high-low)
    
    -- Retest Candle Metrics
    retest_candle_body_penetration NUMERIC,     -- combined body ratio and penetration depth
    
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