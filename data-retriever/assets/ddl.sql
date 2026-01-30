CREATE SCHEMA IF NOT EXISTS trenda;

CREATE TABLE IF NOT EXISTS trenda.forex (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- Lookup table for timeframes
CREATE TABLE IF NOT EXISTS trenda.timeframes (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trenda.aoi_type (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL UNIQUE
);

-- Main trend data table with foreign keys
CREATE TABLE IF NOT EXISTS trenda.trend_data (
    forex_id INTEGER NOT NULL REFERENCES trenda.forex(id) ON DELETE CASCADE,
    timeframe_id INTEGER NOT NULL REFERENCES trenda.timeframes(id) ON DELETE CASCADE,
    trend TEXT,
    high REAL,
    low REAL,
    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(forex_id, timeframe_id)
);

CREATE TABLE IF NOT EXISTS trenda.area_of_interest (
    id SERIAL,
    forex_id INTEGER NOT NULL REFERENCES trenda.forex(id) ON DELETE CASCADE,
    timeframe_id INTEGER NOT NULL REFERENCES trenda.timeframes(id) ON DELETE CASCADE,
    lower_bound REAL,
    upper_bound REAL,
    type_id INTEGER NOT NULL REFERENCES trenda.aoi_type(id) ON DELETE CASCADE,
    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Entry Signal Table (simplified - execution data stored after live execution)
CREATE TABLE IF NOT EXISTS trenda.entry_signal (
    -- Identity
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    direction TEXT NOT NULL,
    -- AOI snapshot (simplified)
    aoi_timeframe TEXT NOT NULL,
    aoi_low REAL NOT NULL,
    aoi_high REAL NOT NULL,
    -- Entry context (stored after live execution)
    entry_price REAL,  -- Live execution price
    atr_1h REAL NOT NULL,
    -- New scoring system
    htf_score REAL,
    obstacle_score REAL,
    total_score REAL,
    -- SL/TP configuration (calculated with live execution price)
    sl_model TEXT,
    sl_distance_atr REAL,  -- Calculated based on signal candle close
    tp_distance_atr REAL,  -- Calculated based on signal candle close
    rr_multiple REAL,
    actual_rr REAL,  -- Actual R:R from execution price (differs from rr_multiple due to price drift)
    price_drift REAL,  -- Price movement from signal candle close to execution (positive = in trade direction)
    -- HTF context
    htf_range_position_daily REAL,
    htf_range_position_weekly REAL,
    distance_to_next_htf_obstacle_atr REAL,
    conflicted_tf TEXT,
    -- Processing flags
    outcome_computed BOOLEAN NOT NULL DEFAULT FALSE,
    -- Meta
    is_break_candle_last BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entry_signal_total_score ON trenda.entry_signal(total_score);
CREATE INDEX IF NOT EXISTS idx_entry_signal_outcome_pending ON trenda.entry_signal (outcome_computed, signal_time);

-- Signal Outcome Table (96 bar window)
CREATE TABLE IF NOT EXISTS trenda.signal_outcome (
    entry_signal_id INTEGER PRIMARY KEY
        REFERENCES trenda.entry_signal(id) ON DELETE CASCADE,

    -- Observation window (96 bars = 4 days)
    window_bars INTEGER NOT NULL,

    -- Extremes (normalized in ATR units)
    mfe_atr REAL NOT NULL,
    mae_atr REAL NOT NULL,

    -- Timing
    bars_to_mfe INTEGER NOT NULL,
    bars_to_mae INTEGER NOT NULL,
    first_extreme TEXT NOT NULL CHECK (first_extreme IN ('MFE_FIRST', 'MAE_FIRST', 'ONLY_MFE', 'ONLY_MAE', 'NONE')),

    -- Checkpoint returns (normalized in ATR units)
    return_after_48 REAL,
    return_after_72 REAL,
    return_after_96 REAL,

    -- Exit tracking
    exit_reason TEXT CHECK (exit_reason IN ('SL', 'TP', 'TIMEOUT')),
    bars_to_exit INTEGER,  -- Bar number when SL or TP was hit

    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signal_outcome_extremes
    ON trenda.signal_outcome(mfe_atr, mae_atr);

-- Failed Signals Table (tracks why signals weren't generated)
CREATE TABLE IF NOT EXISTS trenda.failed_signals (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    failed_signal_time TIMESTAMPTZ NOT NULL,
    direction TEXT,  -- NULL if direction wasn't determined
    
    -- Tradable AOIs snapshot (JSON array of {aoi_high, aoi_low, timeframe})
    tradable_aois JSONB,
    aoi_count INTEGER,  -- Quick count, NULL if AOIs weren't fetched
    
    -- Market context at failure time
    reference_price REAL,  -- Signal candle close (not "entry" since we didn't enter)
    atr_1h REAL,
    
    -- Scoring (NULL if not calculated)
    htf_score REAL,
    obstacle_score REAL,
    total_score REAL,
    
    -- SL/TP config
    sl_model TEXT,
    
    -- HTF context (NULL if not calculated)
    htf_range_position_daily REAL,
    htf_range_position_weekly REAL,
    distance_to_next_htf_obstacle_atr REAL,
    conflicted_tf TEXT,
    
    -- Pattern meta (only if pattern was found but failed later)
    is_break_candle_last BOOLEAN,
    
    -- Failure tracking
    failed_gate TEXT NOT NULL,  -- Structured: TRADE_BLOCKED, NO_CANDLES, INSUFFICIENT_DATA, NO_DIRECTION, NO_AOIS, ZERO_ATR, gate names, etc.
    fail_reason TEXT NOT NULL,  -- Human-readable description
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_failed_signals_symbol_time 
    ON trenda.failed_signals(symbol, failed_signal_time);
CREATE INDEX IF NOT EXISTS idx_failed_signals_gate 
    ON trenda.failed_signals(failed_gate);
