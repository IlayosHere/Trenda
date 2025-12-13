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

CREATE TABLE IF NOT EXISTS trenda.entry_signal (
    -- Identity
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    signal_time TIMESTAMPTZ NOT NULL,
    direction TEXT NOT NULL,
    -- Trend snapshot at signal time
    trend_4h TEXT NOT NULL,
    trend_1d TEXT NOT NULL,
    trend_1w TEXT NOT NULL,
    trend_alignment_strength INTEGER NOT NULL,
    -- AOI snapshot
    aoi_timeframe TEXT NOT NULL,
    aoi_low REAL NOT NULL,
    aoi_high REAL NOT NULL,
    aoi_classification TEXT NOT NULL,
    -- Entry context
    entry_price REAL NOT NULL,
    atr_1h REAL NOT NULL,
    -- Scoring
    final_score REAL NOT NULL,
    tier TEXT NOT NULL,
    outcome_computed BOOLEAN NOT NULL DEFAULT FALSE,
     -- Meta
    is_break_candle_last BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    --SL
    aoi_sl_tolerance_atr REAL NOT NULL,
    aoi_raw_sl_distance_price REAL NOT NULL,
    aoi_raw_sl_distance_atr   REAL NOT NULL,
    aoi_effective_sl_distance_price REAL NOT NULL,  
    aoi_effective_sl_distance_atr   REAL NOT NULL
);

CREATE INDEX idx_entry_signal_score ON trenda.entry_signal(final_score);
CREATE INDEX idx_entry_signal_tier ON trenda.entry_signal(tier);
CREATE INDEX idx_entry_signal_outcome_pending ON trenda.entry_signal (outcome_computed, signal_time);


CREATE TABLE IF NOT EXISTS trenda.entry_signal_score (
    id SERIAL PRIMARY KEY,
    entry_signal_id INTEGER NOT NULL
        REFERENCES trenda.entry_signal(id) ON DELETE CASCADE,

    stage_name TEXT NOT NULL, -- 'S1', 'S2', ..., 'S8'
    raw_score REAL NOT NULL CHECK (raw_score >= 0 AND raw_score <= 1),
    weight REAL NOT NULL CHECK (weight >= 0),
    weighted_score REAL NOT NULL CHECK (weighted_score >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (entry_signal_id, stage_name)
);

CREATE INDEX idx_entry_signal_score_signal
    ON trenda.entry_signal_score(entry_signal_id);

CREATE TABLE IF NOT EXISTS trenda.signal_outcome (
    entry_signal_id INTEGER PRIMARY KEY
        REFERENCES trenda.entry_signal(id) ON DELETE CASCADE,

    -- Observation window
    window_bars INTEGER NOT NULL, -- e.g. 48

    -- Extremes (normalized in ATR units)
    mfe_atr REAL NOT NULL,
    mae_atr REAL NOT NULL,

    -- Timing
    bars_to_mfe INTEGER NOT NULL,
    bars_to_mae INTEGER NOT NULL,
    first_extreme TEXT NOT NULL CHECK (first_extreme IN ('MFE_FIRST', 'MAE_FIRST', 'ONLY_MFE', 'ONLY_MAE', 'NONE')),

    -- Shape / decay checkpoints (normalized returns)
    return_after_3 REAL,
    return_after_6 REAL,
    return_after_12 REAL,
    return_after_24 REAL,
    return_end_window REAL,

    --SL + TP
    bars_to_aoi_sl_hit INTEGER,
    bars_to_r_1   INTEGER,
    bars_to_r_1_5 INTEGER,
    bars_to_r_2   INTEGER,
    aoi_rr_outcome TEXT NOT NULL CHECK (aoi_rr_outcome IN 
    ('TP1_BEFORE_SL', 'TP1_5_BEFORE_SL', 'TP2_BEFORE_SL', 'SL_BEFORE_ANY_TP','NONE')),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_signal_outcome_extremes
    ON trenda.signal_outcome(mfe_atr, mae_atr);

